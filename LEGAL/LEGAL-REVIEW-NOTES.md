# NEXORA legal documents: review notes

These notes go with the Terms of Service and Privacy Policy in `legal-documents.js`. The documents were written to describe how the NEXORA code actually behaves. They are **not legal advice**, and they do not guarantee compliance with the Data Privacy Act of 2012 (RA 10173) or any other law. A qualified Philippine lawyer or data protection professional should review them before NEXORA accepts real customers.

## Placeholders to complete

Each of these is marked `[TO BE COMPLETED BY OPERATOR]` in the documents.

| Placeholder | Where |
|---|---|
| Name of the person or organisation responsible for NEXORA (the personal information controller) | Terms §1, Privacy §1 |
| Postal address | Terms §17 |
| Data Protection Officer's name and contact details | Privacy §1, §14 |
| Venue for disputes | Terms §16 |
| Retention periods for each kind of record | Privacy §9 |
| Response period for data subject requests | Privacy §10 |
| Lawful basis for processing verification details | Privacy §4 |

## Clauses that need qualified review

1. **Consent vs. contract (RA 10173 Sec. 3(b), Sec. 12).** Consent under the Act must be freely given. Requiring "acceptance" of the Privacy Policy to sign in can look like bundled consent. The documents treat the Privacy Policy as something users *acknowledge*, and rely on contract necessity (Sec. 12(b)) and legitimate interest (Sec. 12(f)) as the lawful bases. Confirm that this framing holds up.
2. **DPO designation and NPC registration.** NPC rules require a Data Protection Officer. Whether NEXORA must also register with the National Privacy Commission depends on thresholds such as number of employees and number of data subjects. Confirm before launch.
3. **Breach notification.** Privacy §8 promises notification "as the law requires". Check the NPC breach-management rules (NPC Circular 16-03 and later issuances) for timelines and content.
4. **Cross-border transfer.** The database is in AWS `ap-southeast-1` (Singapore). Check what accountability obligations apply to the controller and its processors (Sec. 21) and whether data-sharing or outsourcing agreements with Supabase and Render are needed.
5. **Minors.** From version 1.1, sign-up refuses anyone under 18 by the date of birth they enter, and existing under-18 accounts cannot book. The date of birth is self-declared until an administrator approves the customer's ID details, so a minor can still lie. Confirm that this is an acceptable age-assurance measure, and how to handle a request from a parent or guardian (Privacy §12).
6. **Limitation of liability.** Civil Code Art. 1171 prevents waiving liability for fraud in advance. Art. 1172 and the Consumer Act (RA 7394) may limit further exclusions. There is deliberately no monetary cap.
7. **Online transactions.** If NEXORA becomes a real commercial platform, review the Internet Transactions Act of 2023 (RA 11967) and the Consumer Act for merchant-identification, pricing, and cancellation disclosures.
8. **Sample content.** The documents say listings, prices, reviews, and cancellation statements are samples. If real inventory, real prices, or real payments are ever introduced, Terms §1, §8, and §9 must be rewritten.
9. **Account deletion.** From version 1.2, customers delete their own account in Settings (`backend/accounts.py`). Deletion is refused while a booking is open. The account row is anonymised and disabled, personal records are erased, past bookings are kept without contact details, and consent records are kept. Privacy §9 describes this. Confirm that keeping anonymised bookings and consent records is justified, and for how long. Also confirm that offering export and deletion to customers who have not accepted an updated policy (Privacy §10) is the intended position.
10. **Academic data use.** If instructors or evaluators will see real user data as part of grading, disclose this in Privacy §4 and §6.
11. **Verification details as sensitive personal information (Sec. 3(l), Sec. 13).** Government-issued identifiers and licenses are listed as sensitive personal information. NEXORA keeps only the ID type, the last 4 characters and the expiry date, but these may still qualify. Processing sensitive personal information is generally prohibited unless a Sec. 13 condition applies. Confirm the lawful basis and complete the placeholder in Privacy §4.
12. **What "verified" means.** NEXORA has no identity verification provider and collects no document images, so an administrator's approval is a decision about typed-in details, not proof of identity or age. Terms §2 and the Verification page say this plainly. The ID types offered (PhilSys, passport, LTO license, UMID, PRC, Postal ID) were chosen for the demonstration, not from a provider's list. Before relying on verification for real customers, use a licensed provider and rewrite Terms §2.
13. **Demo driver's license.** Parking accepts a sample card that NEXORA issues; it does not show that anyone may drive. Administrators can switch it off on the Verifications page, which stops parking reservations until another method exists. Confirm that this is acceptable for a demonstration and must not be used with real parking.
14. **Verification retention.** Privacy §9 says ID digits and expiry dates on rejected, resubmitted or replaced submissions are erased 30 days after review, while the date of birth and the current verification are kept while the account exists. Confirm these periods, especially for an account whose ID was approved and is no longer used.

## Changing a document

1. Edit the text in `legal-documents.js`.
2. For a material change, raise the document's `version` there **and** in `CURRENT_VERSIONS` in `CENTRAL CHANNEL/backend/consent.py`, and update `effective`.
3. Restart the API. Customers whose latest accepted version is older will be asked to review and accept again the next time they use the Service. Their earlier records stay in `PolicyConsents`.
