# Demo images

These are copies of D-Fire validation images, not live CCTV feeds.

- `fire.jpg`: AoF04266.jpg. Contains fire and smoke; some localization misses remain.
- `clear.jpg`: AoF00003.jpg. No fire ground-truth boxes, and no fire prediction >= 0.22 in the earlier CPU validation run. The demo performs fresh actual inference; it does not force a negative result.

The original dataset ZIP, labels and model are untouched. The sample endpoints are disabled when `EMBER_DEMO_ENABLED=false`. Review dataset/model redistribution rights before distributing these assets or making a public service.
