import pytest

from narxnoma.research.targets import category_slug, load_targets

openpyxl = pytest.importorskip("openpyxl")


def test_txt_names_prices_and_comments(tmp_path):
    f = tmp_path / "list.txt"
    f.write_text(
        "# a comment\nSamsung Galaxy A56 8/256GB;5 200 000\n\nXiaomi Redmi 14C\tabc\n"
        "samsung galaxy a56 8/256gb\n",
        encoding="utf-8",
    )
    ts = load_targets(f, default_category="smartphones")
    assert [t.name for t in ts] == ["Samsung Galaxy A56 8/256GB", "Xiaomi Redmi 14C"]  # dup dropped
    assert ts[0].our_price == 5_200_000 and ts[1].our_price is None
    assert all(t.category == "smartphones" for t in ts)


def test_csv_columns_found_by_alias_and_extras_kept(tmp_path):
    f = tmp_path / "list.csv"
    f.write_text(
        "﻿Товар;Наша цена;Категория;Brand group\n"
        "Samsung UE55DU7100UXUZ;6 900 000;телевизоры;Samsung\n",
        encoding="utf-8",
    )
    (t,) = load_targets(f)
    assert t.name == "Samsung UE55DU7100UXUZ"
    assert t.our_price == 6_900_000
    assert t.category == "televisions"
    assert t.extra == {"Brand group": "Samsung"}


def test_xlsx_with_currency(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Product Name", "Price", "Currency"])
    ws.append(["iPhone 16 128GB", 799, "USD"])
    ws.append(["Redmi 14C", 1_500_000, None])
    f = tmp_path / "list.xlsx"
    wb.save(f)
    a, b = load_targets(f, default_category="smartphones")
    assert (a.currency, a.our_price) == ("USD", 799.0)
    assert (b.currency, b.our_price) == ("UZS", 1_500_000.0)


def test_missing_name_column_names_the_options(tmp_path):
    f = tmp_path / "x.csv"
    f.write_text("a,b\n1,2\n", encoding="utf-8")
    with pytest.raises(ValueError, match="product-name column"):
        load_targets(f)


@pytest.mark.parametrize(
    "raw,slug",
    [
        ("Phones", "smartphones"),
        ("ТВ", "televisions"),
        ("acs", "acs"),
        ("кондиционеры", "acs"),
        ("nonsense", None),
        (None, None),
    ],
)
def test_category_slug(raw, slug):
    assert category_slug(raw) == slug


def test_unsupported_extension(tmp_path):
    f = tmp_path / "x.pdf"
    f.write_text("x")
    with pytest.raises(ValueError, match="unsupported"):
        load_targets(f)
