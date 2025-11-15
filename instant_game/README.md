# Lemon Squeeze Instant Game Prototype

Prototype HTML5 game for Facebook Instant Games. Players squeeze a lime within 30 seconds to reach the target juice level and share results for discounts.

## Structure
- `index.html` – loads Phaser, Facebook Instant Game bootstrap, UI shell.
- `styles.css` – responsive layout & share panel styling.
- `game.js` – Phaser 3 scene implementing timer, juice meter, and share hooks.

## Development
1. Serve locally (e.g., `npx serve instant_game`).
2. Test gameplay in mobile browser. FB Instant APIs fall back to mock alerts when not available.

## Facebook Instant Game Setup
1. Zip contents of `instant_game/` and upload as a new Instant Game bundle.
2. In Dashboard → Web Hosting, set entry point to `index.html`.
3. Configure share action reward: on `FBInstant.shareAsync` success, call your POS backend endpoint to issue a discount code and return it to the user.

## Reward Flow Suggestion
1. Modify `share-btn` handler to call `/api/game/reward` with FB player ID.
2. Backend verifies share (via signed request) and returns promo code.
3. Front-end displays the code/QR for redemption at checkout.

Feel free to swap assets, sounds, or integrate analytics events. The Phaser scene is small and can be extended with juice animations, power-ups, or cat mascots to match branding. 
