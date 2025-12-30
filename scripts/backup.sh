#!/bin/bash
# NEXUS WALLET - Database Backup Script

set -e

# Configuration
BACKUP_DIR="/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/nexus_wallet_$DATE.sql.gz"

# Database credentials from environment
DB_HOST="${DB_POSTGRES_HOST:-localhost}"
DB_PORT="${DB_POSTGRES_PORT:-5432}"
DB_USER="${DB_POSTGRES_USER:-nexus}"
DB_NAME="${DB_POSTGRES_DB:-nexus_wallet}"

# Create backup directory
mkdir -p $BACKUP_DIR

# Create backup
echo "Creating backup: $BACKUP_FILE"
PGPASSWORD="${DB_POSTGRES_PASSWORD}" pg_dump \
    -h $DB_HOST \
    -p $DB_PORT \
    -U $DB_USER \
    -d $DB_NAME \
    --format=custom \
    --compress=9 \
    | gzip > $BACKUP_FILE

# Check backup size
BACKUP_SIZE=$(ls -lh $BACKUP_FILE | awk '{print $5}')
echo "Backup created: $BACKUP_FILE ($BACKUP_SIZE)"

# Delete old backups (keep last 7 days)
find $BACKUP_DIR -name "nexus_wallet_*.sql.gz" -mtime +7 -delete
echo "Old backups cleaned up"

# Optional: Upload to S3
if [ ! -z "$AWS_S3_BUCKET" ]; then
    aws s3 cp $BACKUP_FILE s3://$AWS_S3_BUCKET/backups/
    echo "Backup uploaded to S3"
fi

echo "Backup completed successfully!"