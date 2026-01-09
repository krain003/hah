-- NEXUS WALLET Database Initialization

-- Enable extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Grant privileges
GRANT ALL PRIVILEGES ON DATABASE nexus_wallet TO nexus;

-- Create schema (tables will be created by SQLAlchemy)
SELECT 'Database initialized successfully' as status;