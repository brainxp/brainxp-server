import pytest

from app.errors import Invalid
from app.services.documents import classify, method_for

IMAGES = ["image/jpeg", "image/png", "image/webp"]
DOCUMENTS = [
    "application/pdf",
    "text/plain",
    "text/markdown",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/vnd.oasis.opendocument.text",
    "application/vnd.oasis.opendocument.presentation",
]


@pytest.mark.parametrize("media_type", IMAGES)
def test_an_image_always_counts_as_a_photo(media_type):
    assert method_for(classify(media_type)) == "photo", (
        "a parent's rule banning photos must not be sidestepped by picking the "
        "image through the send-document button"
    )


@pytest.mark.parametrize("media_type", DOCUMENTS)
def test_anything_that_is_not_an_image_counts_as_a_document(media_type):
    assert method_for(classify(media_type)) == "document"


def test_an_unknown_type_is_refused_before_it_can_be_assessed():
    with pytest.raises(Invalid):
        classify("application/x-msdownload")
