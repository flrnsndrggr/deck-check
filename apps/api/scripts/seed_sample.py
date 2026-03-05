from __future__ import annotations

import requests

SAMPLE = """Commander
1 Atraxa, Praetors' Voice
Deck
1 Sol Ring
1 Arcane Signet
1 Command Tower
1 Exotic Orchard
1 Swords to Plowshares
1 Cultivate
1 Kodama's Reach
1 Rhystic Study
1 Smothering Tithe
1 Teferi's Protection
1 Farewell
1 Counterspell
1 Swan Song
1 Heroic Intervention
1 Beast Within
1 Vindicate
1 Demonic Tutor
1 Enlightened Tutor
1 Worldly Tutor
1 Cyclonic Rift
1 Toxic Deluge
1 Birds of Paradise
1 Bloom Tender
1 Farseek
1 Nature's Lore
1 Three Visits
1 Fellwar Stone
1 Mana Crypt
1 Mystic Remora
1 Esper Sentinel
1 Mystic Confluence
1 Ponder
1 Brainstorm
1 Preordain
1 Enlightened Tutor
1 Polluted Delta
1 Flooded Strand
1 Windswept Heath
1 Marsh Flats
1 Verdant Catacombs
1 Misty Rainforest
1 Breeding Pool
1 Hallowed Fountain
1 Watery Grave
1 Temple Garden
1 Overgrown Tomb
1 Godless Shrine
1 Command Beacon
1 Reflecting Pool
1 City of Brass
1 Mana Confluence
1 Path to Exile
1 Anguished Unmaking
1 Assassin's Trophy
1 Abrupt Decay
1 Fierce Guardianship
1 Force of Will
1 Pact of Negation
1 Swan Song
1 Mystic Snake
1 Eternal Witness
1 Regrowth
1 Bala Ged Recovery
1 Tymna the Weaver
1 Thrasios, Triton Hero
1 Seedborn Muse
1 Smothering Tithe
1 Mirari's Wake
1 Necropotence
1 Sylvan Library
1 Phyrexian Arena
1 Faeburrow Elder
1 Kinnan, Bonder Prodigy
1 Eladamri's Call
1 Diabolic Intent
1 Finale of Devastation
1 Walking Ballista
1 Heliod, Sun-Crowned
1 Aetherflux Reservoir
1 Bolas's Citadel
1 Sensei's Divining Top
1 Solitude
1 Sire of Stagnation
1 Consecrated Sphinx
1 Oko, Thief of Crowns
1 Teferi, Time Raveler
1 Narset, Parter of Veils
1 Tamiyo, Collector of Tales
1 Ugin, the Spirit Dragon
1 Supreme Verdict
1 Damn
1 Wrath of God
1 Cyclonic Rift
1 Generous Gift
1 Nature's Claim
1 Force of Negation
1 Mental Misstep
1 Island
1 Forest
1 Plains
1 Swamp
"""


def main():
    base = "http://localhost:8000"
    parsed = requests.post(f"{base}/api/decks/parse", json={"decklist_text": SAMPLE, "bracket": 3}).json()
    tagged = requests.post(f"{base}/api/decks/tag", json={"cards": parsed["cards"], "commander": parsed.get("commander"), "global_tags": True}).json()
    sim = requests.post(
        f"{base}/api/sim/run",
        json={
            "cards": tagged["cards"],
            "commander": parsed.get("commander"),
            "runs": 500,
            "turn_limit": 8,
            "policy": "auto",
            "bracket": 3,
            "multiplayer": True,
            "seed": 42,
        },
    ).json()
    print(sim)


if __name__ == "__main__":
    main()
