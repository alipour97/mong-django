import tempfile
from pathlib import Path

from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from apps.adminapi.models import AdminUser
from apps.website.models import CooperationRequest, MediaAttachment


class ResumeDownloadTests(TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        settings = override_settings(MEDIA_ROOT=self.directory.name, MEDIA_URL="/media/", DEBUG=False)
        settings.enable()
        self.addCleanup(settings.disable)
        self.application = CooperationRequest.objects.create(first_name="مریم")
        self.attachment = MediaAttachment.objects.create(
            table=MediaAttachment.Table.COOPERATION_REQUESTS, record_id=self.application.id,
            media_url="/media/resumes/sample.pdf",
        )
        self.file = Path(self.directory.name) / "resumes/sample.pdf"
        self.file.parent.mkdir()
        self.file.write_bytes(b"%PDF-1.7 resume")
        self.url = f"/api/admin/v1/Cooperation/{self.application.id}/Resume"
        self.client = APIClient()
        self.client.force_authenticate(AdminUser.objects.create(username="recruiter", cellphone="09120000001"))

    def test_download_works_in_production_with_attachment_headers(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(b"".join(response.streaming_content), self.file.read_bytes())
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertIn("attachment;", response["Content-Disposition"])
        self.assertEqual(response["Cache-Control"], "private, no-store")

    def test_anonymous_download_is_rejected(self):
        self.client.force_authenticate(user=None)
        self.assertEqual(self.client.get(self.url).status_code, 401)

    def test_missing_file_and_deleted_application_return_404(self):
        self.file.unlink()
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.application.is_deleted = True
        self.application.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_file_paths_cannot_escape_the_media_directory(self):
        self.attachment.media_url = "/media/../outside.pdf"
        self.attachment.save()
        self.assertEqual(self.client.get(self.url).status_code, 404)
