import pytest

from suspensionlab.model.autosave_guard import AutosaveGuard, inspect_autosave


def test_existing_content_requires_approval_and_external_change_relocks(tmp_path):
    path = tmp_path / 'autosave.susp.json'
    guard = AutosaveGuard()
    assert guard.may_write(inspect_autosave(path))
    path.write_bytes(b'prior')
    old = inspect_autosave(path)
    assert old and not guard.may_write(old)
    guard.approve(old, inspect_autosave(path))
    assert guard.may_write(inspect_autosave(path))
    path.write_bytes(b'newer')
    assert not guard.may_write(inspect_autosave(path))
    with pytest.raises(OSError):
        guard.approve(old, inspect_autosave(path))
    assert not guard.may_write(inspect_autosave(path))
    assert path.read_bytes() == b'newer'


def test_exact_contents_but_different_path_are_not_authorized(tmp_path):
    a, b = tmp_path / 'a', tmp_path / 'b'
    a.write_bytes(b'test')
    b.write_bytes(b'test')
    guard = AutosaveGuard()
    stamp = inspect_autosave(a)
    assert stamp is not None
    guard.approve(stamp, inspect_autosave(a))
    assert not guard.may_write(inspect_autosave(b))


def test_invalid_candidates_fail_closed(tmp_path, monkeypatch):
    from suspensionlab.model import autosave_guard as module

    with pytest.raises(OSError):
        inspect_autosave(tmp_path)
    file = tmp_path / 'large'
    file.write_bytes(b'1234')
    monkeypatch.setattr(module, 'MAX_AUTOSAVE_BYTES', 3)
    with pytest.raises(OSError):
        inspect_autosave(file)
    try:
        (tmp_path / 'dangling').symlink_to(tmp_path / 'absent')
    except OSError:
        return
    with pytest.raises(OSError):
        inspect_autosave(tmp_path / 'dangling')


def test_inspect_fails_if_file_changes_during_read(tmp_path, monkeypatch):
    from suspensionlab.model import autosave_guard as module

    path = tmp_path / 'candidate'
    path.write_bytes(b'data')
    original = module.os.fstat
    count = 0
    def changed(fd):
        nonlocal count
        count += 1
        if count == 2:
            path.write_bytes(b'changed')
        return original(fd)
    monkeypatch.setattr(module.os, 'fstat', changed)
    with pytest.raises(OSError):
        module.inspect_autosave(path)
