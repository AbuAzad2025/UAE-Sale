"""
🤖 AI Knowledge Base - قاعدة معرفة أزاد
المساعد الذكي الخبير في المحاسبة والمعدات الثقيلة
"""
import os
from flask import current_app

# تحديد المسار المطلق لمجلد المعرفة (للقراءة فقط — النماذج، الأنماط)
AI_KNOWLEDGE_DIR = os.path.dirname(os.path.abspath(__file__))


def _get_instance_knowledge_dir():
    """مسار مجلد المعرفة القابل للكتابة داخل instance/ (لـPythonAnywhere)."""
    try:
        # داخل سياق التطبيق — نستخدم instance_path
        return os.path.join(current_app.instance_path, 'knowledge')
    except RuntimeError:
        # خارج سياق التطبيق (اختبارات، سكريبتات) — نسقط على مجلد مؤقت
        import tempfile
        return os.path.join(tempfile.gettempdir(), 'azad_knowledge')


def get_knowledge_path(filename):
    """
    الحصول على المسار المطلق لملف داخل مجلد المعرفة.

    قواعد التوجيه:
    - expanded_knowledge/، knowledge_sources.json → instance/knowledge/ (قابل للكتابة)
    - models/، patterns.pkl، memory/ → ai_knowledge/ (للقراءة فقط)
    """
    writable_prefixes = ('expanded_knowledge/', 'knowledge_sources.json')
    if filename.startswith(writable_prefixes):
        base = _get_instance_knowledge_dir()
    else:
        base = AI_KNOWLEDGE_DIR

    path = os.path.join(base, filename)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    return path
