from types import SimpleNamespace

import pytest

from app.main import api
from app.routers.reports import unlocked_new_apps_alert
from app.services import apps as A


def app(package, label, is_system=False, version_name=None):
    return SimpleNamespace(
        package=package, label=label, is_system=is_system, version_name=version_name
    )


def test_a_new_package_reads_as_an_install():
    installed, uninstalled = A.compare({"a": "Alfa"}, {"a": "Alfa", "b": "Beta"})
    assert [x.package for x in installed] == ["b"]
    assert uninstalled == []


def test_a_missing_package_reads_as_an_uninstall():
    installed, uninstalled = A.compare({"a": "Alfa", "b": "Beta"}, {"a": "Alfa"})
    assert installed == []
    assert [x.package for x in uninstalled] == ["b"]


def test_the_uninstalled_label_comes_from_the_stored_row():
    _, uninstalled = A.compare({"com.game": "Free Fire"}, {})
    assert uninstalled[0].label == "Free Fire", (
        "a package that is gone is absent from the latest upload, so its name has to "
        "come from the stored row or the report stops being readable"
    )


def test_an_identical_upload_produces_no_change():
    installed, uninstalled = A.compare({"a": "Alfa", "b": "Beta"}, {"b": "Beta", "a": "Alfa"})
    assert not installed and not uninstalled


def test_renaming_an_app_is_not_a_new_install():
    installed, uninstalled = A.compare({"a": "Alfa"}, {"a": "Alfa Pro"})
    assert not installed and not uninstalled, (
        "an app is identified by its package name; the label changes when the app "
        "updates or the phone language is switched"
    )


def test_duplicate_packages_are_collapsed_so_the_upsert_does_not_clash():
    result = A.deduplicate([app("a", "Old"), app("b", "Beta"), app("a", "New")])
    assert len(result) == 2
    assert {x.package: x.label for x in result}["a"] == "New", (
        "ON CONFLICT DO UPDATE refuses to touch the same row twice in one statement, "
        "so a duplicated upload has to be collapsed first"
    )


def test_the_alert_only_names_apps_that_are_not_locked():
    fresh = [
        {"package": "com.ff", "label": "Free Fire"},
        {"package": "com.ml", "label": "Mobile Legends"},
    ]
    assert unlocked_new_apps_alert(fresh, {"com.ml"}) == (
        "1 aplikasi baru terpasang dan belum dikunci: Free Fire."
    )


def test_the_alert_summarises_a_long_list():
    fresh = [{"package": f"p{i}", "label": f"Aplikasi {i}"} for i in range(5)]
    message = unlocked_new_apps_alert(fresh, set())
    assert message.startswith("5 aplikasi baru terpasang dan belum dikunci: ")
    assert message.endswith("dan 2 lainnya.")


def test_no_new_apps_means_no_alert():
    assert unlocked_new_apps_alert([], set()) is None
    assert unlocked_new_apps_alert([{"package": "a", "label": "Alfa"}], {"a"}) is None


@pytest.fixture(scope="module")
def spec():
    return api.openapi()


def test_the_app_list_reports_its_lock_state(spec):
    props = spec["components"]["schemas"]["InstalledAppOut"]["properties"]
    assert "locked" in props, (
        "the rules screen uses this list as its app picker, so every row has to know "
        "whether it is already locked"
    )
    assert "is_new" in props


def test_uploading_the_app_list_requires_authorization(spec):
    op = spec["paths"]["/devices/apps"]["put"]
    assert any(p.get("name", "").lower() == "authorization" for p in op["parameters"])


def test_an_empty_upload_is_refused_so_the_list_is_not_wiped(spec):
    field = spec["components"]["schemas"]["AppInventoryIn"]["properties"]["apps"]
    assert field["minItems"] == 1, (
        "an empty upload from a broken client would read as every app uninstalled "
        "and would blank the list the parent looks at"
    )
    assert field["maxItems"] == 1000
