-- Logins for the site on SQL Server. Run by hand in SSMS, after setting both passwords.
-- The reader sees the shop's database and nothing else. The writer can add invoices and
-- what they need, and nothing more: no delete anywhere, no change to an existing invoice.
-- The few updates are what the .NET site does to a paid invoice: the coupon or gift card it
-- spent, the variant's Qty (and SalesCount when a voucher paid it all), the default address.
USE master;
GO
IF SUSER_ID('mong_reader') IS NULL CREATE LOGIN mong_reader WITH PASSWORD = 'SET-A-STRONG-PASSWORD';
IF SUSER_ID('mong_writer') IS NULL CREATE LOGIN mong_writer WITH PASSWORD = 'SET-ANOTHER-STRONG-PASSWORD';
GO
USE DadehfaOnlineShop;
GO
IF USER_ID('mong_reader') IS NULL CREATE USER mong_reader FOR LOGIN mong_reader;
ALTER ROLE db_datareader ADD MEMBER mong_reader;

IF USER_ID('mong_writer') IS NULL CREATE USER mong_writer FOR LOGIN mong_writer;
GRANT SELECT, INSERT ON dbo.Customers TO mong_writer;
GRANT SELECT, INSERT ON dbo.CustomerAddresses TO mong_writer;
GRANT UPDATE (IsDefault) ON dbo.CustomerAddresses TO mong_writer;
GRANT SELECT, INSERT ON dbo.Invoices TO mong_writer;
GRANT SELECT, INSERT ON dbo.InvoiceDetails TO mong_writer;
GRANT SELECT, INSERT ON dbo.InvoicePayments TO mong_writer;
GRANT SELECT, INSERT ON dbo.Coupons TO mong_writer;
GRANT UPDATE (IsUsed, UsedDate, IsActive, BankPortalEndTime) ON dbo.Coupons TO mong_writer;
GRANT SELECT ON dbo.GiftCards TO mong_writer;
GRANT UPDATE (GCBalance, IsActive, BankPortalEndTime) ON dbo.GiftCards TO mong_writer;
GRANT SELECT ON dbo.VariantFeatureValues TO mong_writer;
GRANT SELECT, UPDATE (Qty) ON dbo.ProductVariants TO mong_writer;
GRANT SELECT, UPDATE (SalesCount) ON dbo.Products TO mong_writer;
GO
