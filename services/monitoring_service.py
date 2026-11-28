import psutil
import os
from datetime import datetime
from typing import Dict
from extensions import db


class MonitoringService:
    @staticmethod
    def _aggregate_status(database: Dict, disk: Dict, memory: Dict, cpu: Dict) -> str:
        """Worst-status rollup: database failure dominates, any degraded
        resource degrades the whole, otherwise healthy. Shapes of the
        per-check dicts are unchanged."""
        if not database.get("healthy", True):
            return "unhealthy"
        for part in (disk, memory, cpu):
            if not part.get("healthy", True):
                return "degraded"
        return "healthy"

    @staticmethod
    def get_system_health() -> Dict:
        database = MonitoringService.check_database()
        disk = MonitoringService.get_disk_usage()
        memory = MonitoringService.get_memory_usage()
        cpu = MonitoringService.get_cpu_usage()
        return {
            "timestamp": datetime.now().isoformat(),
            "database": database,
            "disk": disk,
            "memory": memory,
            "cpu": cpu,
            "status": MonitoringService._aggregate_status(database, disk, memory, cpu),
        }

    @staticmethod
    def check_database() -> Dict:
        try:
            from sqlalchemy import text

            db.session.execute(text("SELECT 1"))
            return {"status": "connected", "healthy": True}
        except Exception as e:
            return {"status": "error", "healthy": False, "error": str(e)}

    @staticmethod
    def get_disk_usage() -> Dict:
        try:
            from services.health_service import _disk_root

            disk = psutil.disk_usage(_disk_root())
            return {
                "total_gb": round(disk.total / (1024**3), 2),
                "used_gb": round(disk.used / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent": disk.percent,
                "healthy": disk.percent < 90,
            }
        except Exception:
            return {"healthy": True, "error": "unavailable"}

    @staticmethod
    def get_memory_usage() -> Dict:
        try:
            memory = psutil.virtual_memory()
            return {
                "total_mb": round(memory.total / (1024**2), 2),
                "used_mb": round(memory.used / (1024**2), 2),
                "percent": memory.percent,
                "healthy": memory.percent < 85,
            }
        except Exception:
            return {"healthy": True, "error": "unavailable"}

    @staticmethod
    def get_cpu_usage() -> Dict:
        try:
            cpu_percent = psutil.cpu_percent(interval=1)
            return {
                "percent": cpu_percent,
                "cores": psutil.cpu_count(),
                "healthy": cpu_percent < 80,
            }
        except Exception:
            return {"healthy": True, "error": "unavailable"}

    @staticmethod
    def get_application_metrics() -> Dict:
        from models import Sale, Customer, Product
        from models.tenant_scope import TENANT_LESS_SCOPE, get_current_tenant_id

        try:
            tenant_id = get_current_tenant_id()

            def _scoped(query, model):
                """Keep the dashboard counters inside the active tenant.

                A platform owner (tenant None) deliberately sees the whole
                system; a tenant-less context only owns rows with no tenant.
                """
                if tenant_id is None:
                    return query
                if tenant_id == TENANT_LESS_SCOPE:
                    return query.filter(model.tenant_id.is_(None))
                return query.filter(model.tenant_id == tenant_id)

            sales = _scoped(Sale.query, Sale)
            customers = _scoped(Customer.query, Customer)
            products = _scoped(Product.query, Product)
            return {
                "total_sales": sales.count(),
                "total_customers": customers.count(),
                "total_products": products.count(),
                "active_customers": customers.filter_by(is_active=True).count(),
                "low_stock_products": products.filter(
                    Product.current_stock <= Product.min_stock_alert
                ).count(),
            }
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def log_performance_metric(metric_name: str, value: float, tags: Dict = None):
        try:
            basedir = os.path.abspath(
                os.path.join(os.path.dirname(__file__), os.pardir)
            )
            logs_dir = os.path.join(basedir, "logs")
            metrics_file = os.path.join(logs_dir, "performance.log")

            os.makedirs(logs_dir, exist_ok=True)

            with open(metrics_file, "a", encoding="utf-8") as f:
                timestamp = datetime.now().isoformat()
                tags_str = ",".join([f"{k}={v}" for k, v in (tags or {}).items()])
                f.write(f"{timestamp}|{metric_name}={value}|{tags_str}\n")
        except Exception:
            pass
