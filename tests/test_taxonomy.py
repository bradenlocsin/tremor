from tremor.taxonomy import load_taxonomy


def test_taxonomy_shape():
    tax = load_taxonomy()
    ids = [t.id for t in tax.event_types]
    assert len(ids) == len(set(ids))
    assert 10 <= len(ids) <= 15
    first = {t.id for t in tax.event_types if t.first_slice}
    assert first == {"shipping_attack", "military_strike", "chokepoint_disruption"}
    for t in tax.event_types:
        assert t.definition and t.example


def test_region_lookup():
    tax = load_taxonomy()
    assert tax.region_for(12.6, 43.3).id == "red_sea"  # Bab-el-Mandeb
    assert tax.region_for(26.6, 56.3).id == "hormuz"
    assert tax.region_for(24.0, 119.5).id == "taiwan_strait"
    assert tax.region_for(48.85, 2.35) is None  # Paris


def test_candidate_types_use_cameo_and_keywords():
    tax = load_taxonomy()
    ship = tax.candidate_types("195", "https://news.example/houthi-missile-hits-tanker")
    assert "shipping_attack" in {t.id for t in ship}
    no_ship = tax.candidate_types("195", "https://news.example/airstrike-on-sanaa")
    assert "shipping_attack" not in {t.id for t in no_ship}
    assert "military_strike" in {t.id for t in no_ship}
    assert tax.candidate_types("010", "statement") == []
