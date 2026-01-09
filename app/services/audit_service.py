"""
NEXUS WALLET - Audit Service
"""
from datetime import datetime
from sqlalchemy import select, desc
from database.models import AuditLog

class AuditService:
    async def log_action(self, session, admin_id, action, details=None):
        try:
            log = AuditLog(
                admin_id=admin_id, 
                action=action, 
                details=details, 
                created_at=datetime.utcnow()
            )
            session.add(log)
            # Commit делается обычно в хендлере
        except Exception:
            pass

    async def get_logs(self, session, limit=10):
        try:
            result = await session.execute(
                select(AuditLog).order_by(desc(AuditLog.created_at)).limit(limit)
            )
            return result.scalars().all()
        except Exception:
            return []

audit_service = AuditService()