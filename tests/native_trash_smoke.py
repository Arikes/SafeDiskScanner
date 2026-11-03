"""Explicit native integration test; moves only its own temporary fixtures, then restores them."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import uuid

helper = Path(sys.argv[1] if len(sys.argv) > 1 else 'build/trash-helper').resolve()
with tempfile.TemporaryDirectory(prefix='SafeDiskScanner-trash-test-') as tmp:
    root = Path(tmp)
    token = uuid.uuid4().hex
    target = root / 'target'; target.write_text('do not move the link target')
    folder = root / ('folder-' + token); folder.mkdir()
    (folder / 'payload').write_text('folder contents')
    a = root / 'a'; a.mkdir(); b = root / 'b'; b.mkdir()
    name = '中文 \'quote\'\n' + token
    one = a / name; one.write_text('one')
    two = b / name; two.write_text('two')
    link = root / ('link-' + token); link.symlink_to(target)
    paths = [str(p) for p in (one, two, folder, link)] + [str(root / 'missing')]
    result = subprocess.run([str(helper)], input=json.dumps(paths), text=True, capture_output=True, check=True)
    receipts = json.loads(result.stdout)
    try:
        assert [r['path'] for r in receipts] == paths
        assert all(r['trashed'] for r in receipts[:4]), receipts
        assert not receipts[4]['trashed'] and receipts[4]['error'], receipts
        assert not any(os.path.lexists(p) for p in paths[:4])
        destinations = [r['trashPath'] for r in receipts[:4]]
        assert len(set(destinations)) == 4, receipts
        assert Path(destinations[0]).read_text() == 'one'
        assert Path(destinations[1]).read_text() == 'two'
        assert (Path(destinations[2]) / 'payload').read_text() == 'folder contents'
        assert Path(destinations[3]).is_symlink()
        assert target.read_text() == 'do not move the link target'
    finally:
        for receipt in receipts:
            if receipt.get('trashed'):
                os.rename(receipt['trashPath'], receipt['path'])
    assert one.read_text() == 'one' and two.read_text() == 'two'
    assert (folder / 'payload').read_text() == 'folder contents' and link.is_symlink()
print('PASS: native Trash + restore; file, folder, duplicate names, Unicode/newlines, symlink, partial failure')
