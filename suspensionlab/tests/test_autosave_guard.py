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


def test_same_project_file_path_symlink_and_hardlink(tmp_path):
    import os

    from suspensionlab.model.autosave_guard import same_project_file

    shared = tmp_path / 'autosave.susp.json'
    assert same_project_file(shared, tmp_path / '.' / 'autosave.susp.json')
    assert not same_project_file(shared, tmp_path / 'other.susp.json')
    shared.write_bytes(b'important')
    symlink = tmp_path / 'symlink.susp.json'
    try:
        symlink.symlink_to(shared)
    except OSError:
        pass
    else:
        assert same_project_file(shared, symlink)
    hardlink = tmp_path / 'hardlink.susp.json'
    try:
        os.link(shared, hardlink)
    except OSError:
        pass
    else:
        assert same_project_file(shared, hardlink)
        assert hardlink.read_bytes() == shared.read_bytes()


def test_same_project_file_does_not_hide_stat_errors(tmp_path, monkeypatch):
    from pathlib import Path

    from suspensionlab.model.autosave_guard import same_project_file

    a, b = tmp_path / 'a', tmp_path / 'b'
    a.write_text('a')
    b.write_text('b')
    original = Path.stat
    def fail(self, *args, **kwargs):
        if self == b:
            raise PermissionError('denied')
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'stat', fail)
    with pytest.raises(PermissionError):
        same_project_file(a, b)


def test_autosave_path_does_not_create_settings_directory(tmp_path, monkeypatch):
    from suspensionlab import config

    directory = tmp_path / 'not-yet-created'
    monkeypatch.setattr(config, '_base_dir', lambda: directory)
    assert config.autosave_path() == directory / 'autosave.susp.json'
    assert not directory.exists()


def test_reading_may_update_access_time_without_becoming_an_external_change(tmp_path):
    import os
    import time

    path = tmp_path / 'autosave.susp.json'
    path.write_bytes(b'previous-project')
    before = path.stat()
    os.utime(path, ns=(int((time.time() - 86400) * 1_000_000_000), before.st_mtime_ns))
    stamp = inspect_autosave(path)
    assert stamp is not None and path.read_bytes() == b'previous-project'
    assert inspect_autosave(path) == stamp
