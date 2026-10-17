# Everyday Compass

**Useful tools. Trusted resources. Everyday confidence.**

Open `index.html` in a modern browser. No installation or build tools are required. Search works offline. Keep `index.html` and `contact.html` together; upload both to the same folder on your static website host.

## Contact form setup

The Contact page sends name, reply email, topic and message through FormSubmit to **jjkwan118@gmail.com**. It uses normal HTML form submission, built-in required/email validation and FormSubmit's default spam check. Direct email is available as a fallback. No form data is sent until the visitor submits.

1. Publish both HTML files together on your website. Use the hosted page for the delivery test, not a file opened directly from your computer.
2. Submit a test message from Contact.
3. Open the activation email from FormSubmit in **jjkwan118@gmail.com** and confirm the form. Check your spam folder if needed.
4. Submit another test and confirm it arrives in your inbox. Reply to it to check the reply address.

Email delivery is not yet verified: mailbox activation requires your action. FormSubmit handles the submission result on its own page; the hub does not claim success before the service processes it. The form is the one external service dependency; the resource hub itself remains dependency-free. See [FormSubmit's setup documentation](https://formsubmit.co/) for activation details.

## Organisation and design

The homepage moves from the two featured personal tools to four Quick Access destinations, a searchable resource library, practical tips and an explanation of the hub. Navy and teal feature panels distinguish the personal projects; white resource cards show the provider and domain. Large controls, responsive layouts and plain language support users of different ages.

Seven categories: Learning & Education; Seniors & Daily Living; Health & Wellness; Getting Around; Singapore Outings; Games & Brain Activities; Services & Digital Safety. Resources can belong to several categories without duplication in results. The games category currently points to the two personal projects rather than filling the page with unrelated links.

## Add a tool or resource

1. Make a backup of `index.html` and open it in a plain-text editor.
2. Find `ADD NEW TOOL HERE` in the `tools` array, or `ADD USEFUL LINK HERE` in the `resources` array.
3. Copy the preceding object into that array. Keep a comma after each object. Give it a unique `id`, name, short description, complete HTTPS URL and category IDs. Use single quotes around text and escape apostrophes as `\'`.
4. For a tool, set `featured: false` unless it should also appear in the prominent top section. For an external resource, include the provider in `source`. Add search synonyms in `keywords` and optional service details in `note`.
5. Save, reopen in the browser, search for the new entry, and test its link. Counts and category filtering update automatically.

Example tool object (replace every value with your real tool details before adding):

```js
{id:'unique-tool-id', name:'Your tool name', description:'What it helps people do.',
 url:'https://your-real-domain.example/', categories:['learning'],
 audience:'Who it is for', keywords:'useful search synonyms',
 action:'Open tool', featured:false},
```

To add a category, add `{id:'unique-category-id', name:'Category label'}` to `categories`, then assign that ID to one or more entries. Edit `tips` to change the tips. Edit `quickAccess` to reference an existing resource or tool by ID; its URL is reused automatically. Quick Access is currently intended for external resources and labels them accordingly.

## Sources and verification — 21 September 2026

The following official resource pages were retrieved and reviewed online. These links are also the source links in the website cards:

- [HealthHub / Ministry of Health](https://www.healthhub.sg/)
- [Agency for Integrated Care](https://www.aic.sg/)
- [National Library Board](https://www.nlb.gov.sg/main/home)
- [LTA — Getting Around](https://www.lta.gov.sg/content/ltagov/en/getting_around.html)
- [National Parks Board](https://www.nparks.gov.sg/)
- [Visit Singapore / Singapore Tourism Board](https://www.visitsingapore.com/)
- [SG Enable](https://www.sgenable.sg/)
- [ScamShield](https://www.scamshield.gov.sg/)

Both supplied personal app URLs returned HTTP 200. Their descriptions follow the owner's brief; their individual features were not exhaustively tested. External service availability, sign-in requirements and content can change. Update the page's review date only after a new review.

## Checks completed

JavaScript syntax; rendering of all 10 library entries; keyword search; combined external-resource and health-category filters; no-results state; reset behavior; navigation anchor targets; keyboard movement from search to the type selector; mobile visual layout with no horizontal overflow; HTTPS destinations and new-tab isolation (`noopener noreferrer`).

Accessibility provisions include a skip link, semantic landmarks and headings, visible focus, native controls and labels, selected filter announcements, live result counts, 48px control heights, reduced-motion support, responsive reflow and forced-colour borders. This is WCAG 2.2 AA-oriented implementation, not a formal conformance certification. No complete screen-reader or third-party accessibility audit was performed.

## Daily News
The single Show News / Hide News button displays 15 Singapore and 15 World stories from CNA RSS, in publisher feed order. The checked timestamp records successful generation, not the visitor click time. News generation uses only Python standard libraries. Incomplete or failed feed responses leave the previous edition intact and fail the workflow.

GitHub Actions generates and deploys at 06:45, 12:45 and 18:45 Asia/Singapore (22:45, 04:45 and 10:45 UTC). Scheduled starts may be delayed by GitHub. Pushes to main and manual workflow dispatch also generate and deploy. GitHub Pages uses the Actions publishing source. The workflow deploys its artifact directly because commits made with GITHUB_TOKEN do not trigger another Pages build.

## What's On collector

Run `pip install -r requirements.txt` and `python -m playwright install --with-deps chromium` before running `python scripts/run_whats_on.py`. Use `--dry-run` to inspect collection without changing the feed.

The collector reads `sources.json`, follows official event detail links and recognises day-first, month-first and compact date ranges. Gardens and ArtScience have a browser fallback for public JavaScript listings. Verification challenges are not answered; unavailable sources retain their saved records. Finite expired events are removed, unknown-end records are preserved, and a non-empty feed is never replaced with an empty feed.

Each source reports its own collection result and last successful check in `events.json`. A successful workflow means at least one source refreshed; inspect the source rows for partial outages. The workflow still fails when every source fails, after saving safe fallback results. Backup windows retry sources marked as failed even if a fallback feed has a recent timestamp. Collector and test changes on main also run the tests and refresh automatically.

Source settings support up to 20 sites. Every refresh loads the current `sources.json` from main; enabled additions are attempted automatically. Publish the list from the settings page using a repository token with Contents read/write, or download and upload sources.json to main. Publishing triggers a refresh. Saving a browser draft alone does not publish changes. New websites use the generic structured event reader and may require a custom reader if their format is unsupported.
