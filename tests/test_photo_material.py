import io

import pytest
from PIL import Image

from app.errors import Invalid, TooLarge
from app.main import api
from app.services import documents as D

UPLOAD_PATH = "/subjects/{subject_id}/materials"


def photo(width: int = 900, height: int = 1200, fmt: str = "JPEG", **save) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    for y in range(0, height, 40):
        for x in range(0, width, 3):
            image.putpixel((x, y), (30, 30, 30))
    out = io.BytesIO()
    image.save(out, fmt, **save)
    return out.getvalue()


def sideways() -> bytes:
    exif = Image.Exif()
    exif[274] = 6
    return photo(400, 800, exif=exif)


def pages_of(pdf: bytes) -> int | None:
    return D.pdf_page_count(pdf)


@pytest.fixture(scope="module")
def spec():
    return api.openapi()


def test_the_upload_endpoint_takes_a_list_of_files(spec):
    body = spec["paths"][UPLOAD_PATH]["post"]["requestBody"]
    schema = body["content"]["multipart/form-data"]["schema"]
    name = schema["$ref"].rsplit("/", 1)[-1]
    field = spec["components"]["schemas"][name]["properties"]["file"]
    assert field["type"] == "array", (
        "a page photographed on its own is not a lesson; the whole handout has to "
        "arrive as one material"
    )
    assert field["items"]["contentMediaType"] == "application/octet-stream"


def test_the_form_field_is_still_named_file(spec):
    schema = spec["paths"][UPLOAD_PATH]["post"]["requestBody"]["content"]["multipart/form-data"]
    name = schema["schema"]["$ref"].rsplit("/", 1)[-1]
    assert set(spec["components"]["schemas"][name]["required"]) == {"file"}, (
        "a client that sends one part named file must keep working unchanged"
    )


async def test_six_photos_become_one_pdf_of_six_pages():
    merged = await D.photos_to_pdf([photo() for _ in range(6)])
    assert merged.startswith(b"%PDF")
    assert pages_of(merged) == 6


@pytest.mark.parametrize("count", [1, 2, 5, 20])
async def test_the_page_count_follows_the_number_of_photos(count):
    assert pages_of(await D.photos_to_pdf([photo() for _ in range(count)])) == count


def test_the_page_counter_does_not_count_the_page_tree():
    one_page = (
        b"%PDF-1.4\n<</Type /Pages /Kids [3 0 R] /Count 1>>\n<</Type /Page /Parent 2 0 R>>\n"
    )
    assert pages_of(one_page) == 1, (
        "/Type /Pages contains /Type /Page, so counting the substring reported one "
        "page too many for every PDF"
    )


def test_something_that_is_not_a_pdf_has_no_page_count():
    assert pages_of(photo()) is None


async def test_photos_of_mixed_formats_still_merge():
    parts = [photo(fmt="JPEG"), photo(fmt="PNG"), photo(fmt="WEBP")]
    assert pages_of(await D.photos_to_pdf(parts)) == 3


async def test_a_big_photo_is_scaled_down_to_the_vision_limit():
    big = photo(4000, 3000)
    merged = await D.photos_to_pdf([big, big])
    assert len(merged) < len(big) * 2, (
        "the model resizes anything past its vision limit anyway, so shipping full "
        "camera resolution only burns the upload ceiling"
    )
    page = D._page(big)
    assert max(page.size) == D.PHOTO_LONG_EDGE


def test_a_small_photo_is_left_at_its_own_size():
    assert D._page(photo(600, 800)).size == (600, 800)


def test_a_sideways_photo_is_turned_upright():
    assert D._page(sideways()).size == (800, 400), (
        "a phone writes the rotation into EXIF instead of the pixels; unread, the "
        "page reaches the model on its side"
    )


def test_a_photo_that_cannot_be_read_is_refused():
    with pytest.raises(Invalid):
        D._page(b"not an image at all")


@pytest.mark.parametrize("media_type", ["image/heic", "image/heif"])
def test_heic_is_refused_before_the_merge(media_type):
    with pytest.raises(Invalid) as caught:
        D.batch_method([media_type, media_type])
    assert "HEIC" in caught.value.detail["message"]


def test_one_document_on_its_own_is_still_a_document():
    assert D.batch_method(["application/pdf"]) == "document"
    assert D.batch_method(["image/jpeg"]) == "photo"


def test_several_photos_count_as_one_photo_upload():
    assert D.batch_method(["image/jpeg", "image/png", "image/webp"]) == "photo", (
        "a rule banning photos must still catch a batch of them"
    )


def test_documents_cannot_be_sent_in_a_batch():
    with pytest.raises(Invalid) as caught:
        D.batch_method(["application/pdf", "application/pdf"])
    assert caught.value.detail["code"] == "mixed_upload"


def test_a_photo_cannot_smuggle_a_document_alongside_it():
    with pytest.raises(Invalid) as caught:
        D.batch_method(["image/jpeg", "application/pdf"])
    assert caught.value.detail["code"] == "mixed_upload"


def test_a_batch_has_a_ceiling():
    D.batch_method(["image/jpeg"] * D.MAX_PHOTOS)
    with pytest.raises(Invalid) as caught:
        D.batch_method(["image/jpeg"] * (D.MAX_PHOTOS + 1))
    assert caught.value.detail["code"] == "too_many_photos"


def test_an_empty_batch_is_refused():
    with pytest.raises(Invalid):
        D.batch_method([])


def test_one_file_is_hashed_exactly_as_before():
    data = photo()
    assert D.content_digest([data]) == D.sha256_bytes(data), (
        "materials already in the library were hashed this way; a new formula would "
        "make every one of them look unseen"
    )


def test_the_same_photos_hash_the_same_way():
    parts = [photo(width) for width in (300, 400, 500)]
    assert D.content_digest(parts) == D.content_digest(list(parts)), (
        "an identical resend has to be recognised, that is what lowers the reward "
        "for repeating a material"
    )


def test_reordering_the_photos_makes_another_material():
    first, second = photo(300), photo(400)
    assert D.content_digest([first, second]) != D.content_digest([second, first]), (
        "page order is part of the content"
    )


def test_a_batch_hash_is_not_the_hash_of_any_single_photo():
    parts = [photo(300), photo(400)]
    assert D.content_digest(parts) not in {D.sha256_bytes(p) for p in parts}


def test_the_size_guard_reads_a_total():
    D.guard_size(10, 10)
    with pytest.raises(TooLarge):
        D.guard_size(11, 10)


async def test_the_merged_pdf_reaches_the_model_untouched():
    merged = await D.photos_to_pdf([photo(), photo()])
    data, media_type = await D.to_attachment_bytes(data=merged, media_type="application/pdf")
    assert data == merged
    assert media_type == "application/pdf"
