# Setting up the Google Sheet store

One-time setup. ~15 minutes. No WSU IT involved.

The app talks to one Google Sheet as a "robot" (a *service account*) — a
Google identity that isn't a person and only has access to sheets you
explicitly share with it. Nothing here touches your normal Google login's
access.

---

## Part 1 — create the robot (Google Cloud)

1. Go to <https://console.cloud.google.com> and sign in.
   Try your WSU account first. If it blocks you at any step below, use a
   personal Google account instead — the robot doesn't need to be "inside"
   WSU, it just needs to be shared on the Sheet.
2. Top bar → the project dropdown → **New Project**. Name it `ia-mapping`.
   **Create**. Wait ~20 seconds, then make sure that project is selected.
3. In the top search bar, find **Google Sheets API** → **Enable**.
4. Search **Google Drive API** → **Enable**. (The library needs it.)
5. Left menu → **APIs & Services** → **Credentials**.
6. **+ Create Credentials** → **Service account**.
   - Name: `ia-mapping-sheet` → **Create and continue**.
   - Skip the optional "grant access" steps → **Done**.
7. Back on the Credentials page, click the new service account under
   **Service Accounts**.
8. **Keys** tab → **Add key** → **Create new key** → **JSON** → **Create**.
   A `.json` file downloads. **This is the password.** Don't email it, don't
   paste it into chat, don't commit it.
9. Copy the service account's **email** — it looks like
   `ia-mapping-sheet@ia-mapping-xxxxx.iam.gserviceaccount.com`.

> If step 8 fails with "key creation disabled by policy", that's a WSU org
> restriction — redo Parts 1–2 signed in with a personal Google account.

---

## Part 2 — create the Sheet

1. Go to <https://sheets.new>. Name it e.g. **IA Mapping — working data**.
2. Leave it empty. The app writes the header row and columns on first run.
3. **Share** (top right) → paste the robot email from step 9 → set it to
   **Editor** → **Send**. (It won't receive an email — that's expected.)
4. Copy the **Sheet ID** from the URL — the long string between `/d/` and
   `/edit`:
   `https://docs.google.com/spreadsheets/d/`**`1AbC…xyz`**`/edit`

> **Where should the Sheet live?** If WSU has Google Workspace, create it in
> your WSU Drive so the data stays on WSU-controlled storage. Otherwise a
> personal Drive is fine for the pilot — it's the same data that already goes
> onto Streamlit Cloud.

---

## Part 3 — wire it into the app

1. In the repo, copy `.streamlit/secrets.toml.example` to
   `.streamlit/secrets.toml`.
2. Open the downloaded `.json` in a text editor. Copy each value into the
   matching line in `secrets.toml` (the layout matches the JSON).
3. Paste the **Sheet ID** into the `[sheet] id = "…"` line.
4. `.streamlit/secrets.toml` is git-ignored — it stays on your machine and,
   later, gets pasted into the Streamlit Cloud app's own Secrets box.

---

## Part 4 — hand back

Reply with:

- the **Sheet ID** (not secret)
- the **service account email** (not secret)

Keep the `.json` on your machine. The smoke test reads credentials from
`.streamlit/secrets.toml` locally, writes one test row to the Sheet, reads it
back, and deletes it.
