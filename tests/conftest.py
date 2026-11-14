import pytest


@pytest.fixture(autouse=True)
def isolated_evaluation_database(tmp_path_factory, monkeypatch):
    database_file = tmp_path_factory.mktemp("bidveil-db") / "bidveil-test.sqlite3"
    monkeypatch.setenv("BIDVEIL_DB_PATH", str(database_file))
    import storage

    storage.initialize_database()
