"""Uploaded assets must be partitioned by tenant."""

import io

from flask import g
from werkzeug.datastructures import FileStorage


PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def _png(filename="logo.png"):
    return FileStorage(stream=io.BytesIO(PNG_BYTES), filename=filename)


def test_save_uploaded_file_partitions_by_tenant(app, tmp_path):
    from utils.helpers import save_uploaded_file

    app.config["UPLOAD_ROOT"] = str(tmp_path)
    with app.test_request_context("/"):
        g.tenant_id = 7
        path = save_uploaded_file(_png(), "logos", allowed_extensions={".png"})

    assert path.startswith("tenant_7/logos/"), path
    assert (tmp_path / path).is_file()


def test_save_uploaded_file_without_tenant_stays_unpartitioned(app, tmp_path):
    from utils.helpers import save_uploaded_file

    app.config["UPLOAD_ROOT"] = str(tmp_path)
    with app.test_request_context("/"):
        g.tenant_id = None
        path = save_uploaded_file(_png(), "logos", allowed_extensions={".png"})

    assert not path.startswith("tenant_"), path


def test_owner_brand_uploads_use_tenant_partition():
    src = open("routes/owner.py", encoding="utf-8").read()

    assert 'tenant_prefix = f"tenant_{tenant_id}"' in src
    assert 'f"{tenant_prefix}/uploads/logos/{filename}"' in src
    assert 'f"{tenant_prefix}/uploads/watermarks/{filename}"' in src


def test_tenant_asset_skeleton_exists():
    from pathlib import Path

    base = Path("static/uploads/tenant_2/uploads")
    assert (base / "logos" / ".gitkeep").is_file()
    assert (base / "watermarks" / ".gitkeep").is_file()
    assert (base / "products" / ".gitkeep").is_file()
