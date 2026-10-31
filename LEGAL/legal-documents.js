/*
 * NEXORA Terms of Service and Privacy Policy.
 *
 * The versions here must match CURRENT_VERSIONS in CENTRAL CHANNEL/backend/consent.py.
 * When a document changes materially, raise its version in BOTH places so customers are
 * asked to review and accept it again. Earlier acceptances stay in PolicyConsents.
 *
 * Text in [square brackets] must be completed by the operator before public launch.
 * See LEGAL/LEGAL-REVIEW-NOTES.md for clauses that need qualified legal review.
 */
(() => {
  const CONTACT_EMAIL = "nexorahotel@gmail.com";
  const contact = `<a href="mailto:${CONTACT_EMAIL}">${CONTACT_EMAIL}</a>`;

  const terms = `
<p class="legal-lede">These Terms explain the rules for using NEXORA to reserve hotel stays and parking spaces. Please read them in full. They are written in plain language, but they are still a binding agreement between you and NEXORA.</p>

<h3>1. About NEXORA and these Terms</h3>
<p>NEXORA ("NEXORA", "we", "us") is an online platform for reserving hotel rooms and parking spaces. It is provided by [TO BE COMPLETED BY OPERATOR: name of the person, team, or organisation responsible for NEXORA].</p>
<p><strong>NEXORA is a student software project built for academic and demonstration purposes.</strong> Unless we clearly state otherwise inside the Service, the properties, photographs, prices, ratings, guest reviews, cancellation statements, and map locations shown are samples used to demonstrate the system. They do not describe real accommodation or parking facilities offered for sale.</p>
<p>These Terms apply to customer accounts on the NEXORA website and the NEXORA Android app (together, the "Service"). By ticking the acceptance box and selecting Continue, you agree to these Terms. If you do not agree, select Cancel. You will not be able to create an account or sign in, but nothing else happens.</p>
<p>How we handle personal information is explained separately in the NEXORA Privacy Policy.</p>

<h3>2. Who can use NEXORA, and verification</h3>
<p>You must be at least 18 years old to create an account. When you sign up, you give your date of birth. NEXORA works out your age from it and does not create accounts for anyone under 18. Customers who signed up before this rule are asked for their date of birth the next time they sign in.</p>
<p>Before you can make or change a reservation, your account must meet these requirements:</p>
<ul>
<li><strong>Hotel:</strong> you are 18 or over according to the date of birth on file, a NEXORA administrator has approved the ID details you submitted, and that ID has not expired.</li>
<li><strong>Parking, including a parking add-on to a hotel stay:</strong> all of the hotel requirements, plus a driver's license. In this demonstration the license requirement is met by a sample "demo driver's license" that NEXORA issues to your account. It is not a real license and does not show that you may drive.</li>
</ul>
<p><strong>Verification in NEXORA is a demonstration.</strong> NEXORA has no identity verification provider. It never asks for photos of your documents or your full ID number, so an approval records an administrator's decision about the details you typed in. It does not prove who you are. Submit only details of your own, valid ID.</p>
<p>Once saved, your date of birth can be changed only after an administrator reopens your verification. Administrators may approve your ID, reject it, or ask you to submit it again, and they give you a reason when they reject it or ask again. You can always cancel an existing reservation, even if your verification lapses.</p>
<p>Staff accounts (Hotel Personnel, Parking Personnel, and Administrator) are assigned by a NEXORA administrator and are governed by separate arrangements with the people who operate NEXORA.</p>

<h3>3. Creating and keeping an account</h3>
<p>To register, you provide your full name, a username, an email address, and a password. You agree that this information is accurate and belongs to you. Each account is for one person. Do not create an account for someone else without their authority.</p>
<p>We may ask you to confirm your email address with a six-digit code or a confirmation link before you can sign in.</p>

<h3>4. Account security and your password</h3>
<ul>
<li>Your password must be at least 10 characters and may use letters, numbers, and the symbols #, * and _.</li>
<li>Passwords are verified by our authentication provider, Supabase Auth. NEXORA's database does not store your password, and NEXORA staff cannot see it.</li>
<li>Keep your password private. Do not share it or reuse it on other sites. Log out when you use a shared device.</li>
<li>After you sign in, a session key is kept in your browser's local storage until you log out or it expires.</li>
<li>If you think someone else has used your account, reset your password with <em>Forgot password?</em> on the sign-in page and tell us at ${contact}.</li>
</ul>
<p>You are responsible for activity under your account unless it results from our failure to protect the Service, or happens after you have told us the account was compromised.</p>

<h3>5. Hotel reservations</h3>
<ul>
<li>A hotel reservation request includes the property, room type, check-in and check-out dates, and number of guests (from 1 to 16). Check-out must be after check-in.</li>
<li>If a room is available for your dates, the system automatically approves the request and assigns a specific room. If no room is available, the request stays <em>Pending</em> for hotel staff or an administrator to review. They may accept, assign, or reject it.</li>
<li>You request a room type. The specific room number is assigned by the system or by staff.</li>
<li><strong>Parking add-on.</strong> During hotel checkout you may add parking for the same stay. The parking window must fall within your hotel stay. A combined reservation is saved only if both a room and a parking space are available; otherwise neither is saved. The two reservations are linked and share one QR pass. The add-on has a flat price, which is saved with your reservation.</li>
</ul>

<h3>6. Parking reservations</h3>
<ul>
<li>A parking reservation includes the date, arrival time, exit time, vehicle type, and licence plate number. One reservation may last at most 7 days.</li>
<li>You may choose a specific space from the live space map or accept any available space. Availability is checked again when you book. If your chosen space was taken in the meantime, the reservation is not saved and you can choose another.</li>
<li>The plate number you enter is registered to your account. A plate that is already registered to another NEXORA account cannot be used.</li>
<li>The space is for the vehicle you identified, during the time you reserved.</li>
</ul>

<h3>7. Booking confirmation and QR passes</h3>
<ul>
<li>Every reservation receives a reference number. Hotel references start with HTL and parking references with PKG.</li>
<li>Your reservation is confirmed only when its status is <em>Approved</em>. <em>Pending</em> and <em>Processing</em> mean it is still being reviewed.</li>
<li>Each reservation has a QR pass, available under My bookings. Staff may scan it to verify your reservation. The pass contains your reservation details, including your name, email address, room or space, plate number, and dates, so treat it like a ticket and do not post it publicly.</li>
</ul>

<h3>8. Changes and cancellation</h3>
<ul>
<li>You can cancel your own reservation from My bookings, using Manage, while its status is <em>Pending</em>, <em>Processing</em>, or <em>Approved</em>. Reservations that are <em>Checked In</em>, <em>Completed</em>, <em>Rejected</em>, or already <em>Cancelled</em> cannot be cancelled in the Service.</li>
<li>Cancellation statements shown on listings, such as "Free cancellation until 24 hours before check-in" or "Non-refundable rate", are sample text. The Service does not currently enforce cancellation deadlines or charge cancellation fees.</li>
<li>Hotel or parking staff and administrators may reject pending requests and may cancel, reassign, check in, or complete reservations for their department.</li>
<li>An administrator may temporarily pause reservations. While they are paused, you cannot create or look up bookings.</li>
</ul>

<h3>9. Prices and payment</h3>
<ul>
<li>Prices are shown in US dollars by default. You may choose to display them in euros, pounds sterling, or Philippine pesos. Those amounts use indicative exchange rates from a third-party service and are for information only.</li>
<li>Displayed totals include sample taxes and fees.</li>
<li>When you book, our server records the total for your reservation in US dollars from its own price list. That recorded amount, not a converted display amount, is the price of the reservation.</li>
<li><strong>NEXORA does not collect, charge, process, or refund payments, and never asks for card details.</strong> At checkout you may select Cash or Bank transfer as your intended payment method. The payment status starts as <em>Pending</em>. Staff may update it to record a payment, a failed payment, or a refund handled outside the Service.</li>
<li>Any payment you arrange directly with a property or facility is outside the Service and these Terms.</li>
</ul>

<h3>10. Prohibited activities</h3>
<p>You must not:</p>
<ul>
<li>give false information or pretend to be someone else, including a false date of birth or ID details that are not your own;</li>
<li>make reservations you do not intend to use, or reserve inventory just to block other users;</li>
<li>access, or try to access, another person's account, reservations, or data;</li>
<li>probe, scan, or test the Service for weaknesses, or try to get around its security, rate limits, role checks, consent requirements, or verification requirements;</li>
<li>use automated tools to scrape the Service or to send large numbers of requests;</li>
<li>upload malicious code or interfere with the Service's operation;</li>
<li>copy, alter, or forge QR passes;</li>
<li>send abusive, threatening, or spam messages through the support report form; or</li>
<li>use the Service for anything unlawful.</li>
</ul>

<h3>11. Service availability</h3>
<p>The Service is provided "as is" and "as available". It runs on demonstration hosting that may go to sleep when idle, so the first request after a quiet period can be slow. The Service may also be unavailable during maintenance, or if one of the providers it depends on, such as its database, authentication, hosting, or email provider, has a problem.</p>
<p>The Help &amp; service page lets you check whether the booking service is responding and report a problem.</p>

<h3>12. Your responsibilities</h3>
<ul>
<li>Keep your account details, vehicle details, and plate number accurate.</li>
<li>Check each reservation's details and status before you travel.</li>
<li>Have your QR pass ready on arrival.</li>
<li>Follow the rules of the property or parking facility.</li>
<li>Report problems through the Help &amp; service page or by email.</li>
</ul>

<h3>13. Suspension and termination</h3>
<p>We may suspend or deactivate an account that breaks these Terms, puts the Service or other users at risk, or must be closed by law. Where it is safe and lawful, we will tell you why.</p>
<p>You may stop using NEXORA at any time. You can delete your account yourself from <em>Settings</em> by entering your password; deletion is not available while you have a pending, approved, or checked-in reservation, so cancel or complete it first. You may also ask us to close your account at ${contact}. Deletion cannot be undone. What happens to your information afterwards is explained in the Privacy Policy.</p>

<h3>14. Limitation of liability</h3>
<p>As far as Philippine law permits, NEXORA is not liable for indirect or consequential loss arising from your use of the Service, from the sample content described in section 1, or from the failure of third-party services we rely on.</p>
<p>Nothing in these Terms limits liability for fraud, bad faith, or gross negligence, or any other liability that cannot be limited or waived under Philippine law.</p>

<h3>15. Changes to these Terms</h3>
<p>Each version of these Terms has a version number and an effective date. If we change them in a way that matters, we will raise the version number, and you will be asked to review and accept the new version before you can continue using your account. We keep a record of each version you have accepted.</p>

<h3>16. Governing law</h3>
<p>These Terms are governed by the laws of the Republic of the Philippines. [TO BE COMPLETED BY OPERATOR: venue for disputes, if any.]</p>

<h3>17. Contact and support</h3>
<p>Questions about these Terms: ${contact}, or the report form on the Help &amp; service page.</p>
<p>[TO BE COMPLETED BY OPERATOR: postal address of the person or organisation responsible for NEXORA.]</p>
`;

  const privacy = `
<p class="legal-lede">This Privacy Policy explains what personal information NEXORA collects, why, where it is kept, who can see it, and the rights you have under the Philippine Data Privacy Act of 2012 (Republic Act No. 10173). It describes how the system actually works today.</p>

<h3>1. Who is responsible for your information</h3>
<p>NEXORA is a student software project built for academic and demonstration purposes.</p>
<p>The personal information controller is [TO BE COMPLETED BY OPERATOR: name of the person or organisation responsible for NEXORA].</p>
<p>Data Protection Officer: [TO BE COMPLETED BY OPERATOR: name and contact details].</p>
<p>Privacy questions and requests: ${contact}.</p>

<h3>2. What this policy covers</h3>
<p>This policy covers customers using the NEXORA website and the NEXORA Android app. Staff accounts are covered by separate arrangements.</p>

<h3>3. Information we collect</h3>
<p><strong>Account information.</strong></p>
<ul>
<li>Your full name, username, email address, and account role, and when you created the account.</li>
<li>A phone number, only if you choose to add one in <em>Settings</em>.</li>
<li>Your password is handled by our authentication provider, Supabase Auth. NEXORA's own database does not store it.</li>
</ul>
<p><strong>Hotel reservations.</strong></p>
<ul>
<li>Guest name and email (taken from your account), property, room type, check-in and check-out dates, number of guests, and the room option you chose.</li>
<li>The total our server recorded for the reservation, your chosen payment method, the payment status staff record, assigned room and floor, and reservation status and history.</li>
<li>Which staff member handled the reservation, and any notes staff add to it.</li>
</ul>
<p><strong>Parking reservations and vehicles.</strong></p>
<ul>
<li>Vehicle type, licence plate number (linked to your account), parking date, arrival and exit times, assigned space, and reservation status and history.</li>
<li>If you add parking to a hotel stay, the two reservations are linked.</li>
</ul>
<p><strong>QR passes.</strong> For each reservation we generate a pass containing your username, email, guest name, room and floor, parking space, plate number, and dates.</p>
<p><strong>Support reports.</strong> The category and message you submit, an optional technical request reference, and any replies from administrators.</p>
<p><strong>Age and identity verification.</strong></p>
<ul>
<li>Your date of birth. We work out your age from it each time you book; we do not store your age.</li>
<li>For ID verification: the type of ID you chose, the last 4 characters of its number, and its expiry date (or that it has none).</li>
<li>Whether the demo driver's license was issued to your account, and when it expires.</li>
<li>The status of each verification, which administrator reviewed it and when, any reason they gave, and a history of these steps that cannot be edited.</li>
</ul>
<p><strong>Consent records.</strong> Which version of the Terms of Service and this Privacy Policy you were shown, whether you scrolled to the end of each, that you ticked the acceptance box, which flow you were in (sign-up, sign-in, or renewal), and the time our server recorded it.</p>
<p><strong>Technical records.</strong></p>
<ul>
<li>For each request to our API we log a request ID, your account ID if you are signed in, the type of request, the page or address requested, the result, how long it took, and the time.</li>
<li>These logs do not include your password, sign-in keys, the content you submit, or your IP address.</li>
<li>Your IP address is used briefly to limit repeated requests, such as sign-in attempts. Those counters expire automatically, within one hour under the default settings.</li>
<li>Administrators can also see a record of privileged staff actions.</li>
</ul>
<p><strong>Kept only on your device.</strong> Some information never leaves your browser unless you send it in a request:</p>
<ul>
<li>your sign-in session keys;</li>
<li>a copy of your display name and email;</li>
<li>your profile photo, which is resized and stored in your browser and is not uploaded to NEXORA;</li>
<li>your theme and currency choices; and</li>
<li>saved exchange rates.</li>
</ul>
<p><strong>What we do not collect.</strong> NEXORA does not ask for payment card or bank details, photos or scans of identification documents, full ID numbers, selfies or other biometric information, or your device location. We do not require a phone number. The partial ID details described above may still count as sensitive personal information under the Data Privacy Act, which is why we keep them to a minimum and erase them when they are no longer needed (section 9).</p>

<h3>4. Why we use your information</h3>
<ul>
<li><strong>To provide your account and reservations:</strong> creating and signing in to your account, assigning rooms and parking spaces, issuing QR passes, and letting staff manage your reservations. This is necessary to provide the Service you asked for (RA 10173, Sec. 12(b)).</li>
<li><strong>To check that you may book:</strong> confirming that you are 18 or over, that an administrator has approved your ID details, and, for parking, that a driver's license is on your account. We use these details for nothing else. [TO BE COMPLETED BY OPERATOR: confirm the lawful basis for processing these details, including under Sec. 13 if they are sensitive personal information.]</li>
<li><strong>To communicate with you:</strong> email confirmation codes, sign-in codes, password recovery codes, and replies to your support reports.</li>
<li><strong>To keep the Service secure and working:</strong> limiting repeated requests, keeping activity and audit logs, and investigating problems you report. This is in NEXORA's legitimate interest (Sec. 12(f)).</li>
<li><strong>To record your acceptance of these documents</strong> and show which versions you accepted.</li>
</ul>
<p>We do not sell your personal information, use it for advertising, or build marketing profiles. Reservations are approved automatically based only on room or space availability. No decision about you is based on profiling.</p>

<h3>5. Where your information is stored and how it is processed</h3>
<ul>
<li>Account, reservation, vehicle, QR pass, support, consent, and log records are stored in a PostgreSQL database run by Supabase. It is hosted on Amazon Web Services in the Asia Pacific (Singapore) region, so <strong>your information is transferred to and stored outside the Philippines</strong>.</li>
<li>Sign-in is handled by Supabase Auth.</li>
<li>The NEXORA API server runs with a cloud hosting provider. The project's deployment configuration uses Render.</li>
<li>Your browser talks only to the NEXORA API. It never connects to the database directly.</li>
<li>When you use the deployed website, connections are encrypted with HTTPS.</li>
</ul>

<h3>6. Who can see your information</h3>
<ul>
<li><strong>You:</strong> your own account, reservations, QR passes, and support reports.</li>
<li><strong>Hotel Personnel:</strong> hotel reservations, including guest name, email, dates, and room.</li>
<li><strong>Parking Personnel:</strong> parking reservations, including vehicle type and plate number.</li>
<li><strong>Administrators:</strong> all reservations, user accounts and roles, support reports, audit records, API activity records, and verification records (date of birth, ID type, last 4 characters, expiry date, and review history). Hotel and Parking Personnel cannot see verification records.</li>
<li><strong>Staff scanning a QR pass:</strong> the details on that pass.</li>
<li><strong>Service providers</strong> listed in section 7, only as needed to run the Service.</li>
<li><strong>Government authorities</strong>, when the law requires it.</li>
</ul>
<p>Our server checks every request against your role. Customers can only see and change their own reservations.</p>

<h3>7. Third-party services</h3>
<ul>
<li><strong>Supabase:</strong> database and sign-in (account, reservation, and consent records).</li>
<li><strong>Render:</strong> hosting for the NEXORA API.</li>
<li><strong>Google:</strong>
  <ul>
  <li>Gmail, used to send account emails and support report emails and replies, when configured.</li>
  <li>Google Maps, embedded on listing pages.</li>
  <li>Google Fonts, used for the site's typefaces.</li>
  </ul>
  When your browser loads a map or font, Google receives your IP address and browser details and may set its own cookies, under Google's privacy policy.</li>
<li><strong>Frankfurter:</strong> an exchange-rate service. Your browser requests rates directly, which shares your IP address but no account information.</li>
<li><strong>Cloudflare (cdnjs):</strong> serves the 3D graphics library used by the hotel walkthrough. Your browser's request shares your IP address.</li>
<li><strong>Redis:</strong> if the operator enables it, a shared store for the short-lived request counters described in section 3.</li>
</ul>

<h3>8. How we protect your information</h3>
<ul>
<li>Passwords are managed by Supabase Auth, not stored by NEXORA.</li>
<li>Sign-in sessions use keys that expire and can be revoked when you log out.</li>
<li>Every protected request is checked on our server for your identity and role.</li>
<li>Sign-in, registration, verification codes, password recovery, and support reports are rate-limited.</li>
<li>Logs exclude passwords, sign-in keys, and request contents, and QR pass codes are hidden in logged addresses.</li>
<li>Consent records and verification history cannot be edited once saved.</li>
<li>Verification records are kept in database tables that browsers and Supabase's public interfaces cannot reach. You cannot change your own verification status, and administrators cannot approve their own.</li>
<li>Database credentials are never sent to your browser.</li>
</ul>
<p>No system is perfectly secure. If a personal data breach occurs that the law requires us to report, we will notify the National Privacy Commission and affected users as the law requires.</p>

<h3>9. How long we keep information</h3>
<ul>
<li>NEXORA does not yet have an automatic deletion schedule. Account, reservation, vehicle, QR pass, and support records are kept while your account exists and for as long as needed for the purposes above. [TO BE COMPLETED BY OPERATOR: specific retention periods.]</li>
<li>Consent records are kept for as long as your account exists, and afterwards for as long as needed to show which versions you accepted.</li>
<li>The last 4 characters and expiry date of an ID submission that was rejected, sent back for resubmission, or replaced by a newer one are erased automatically 30 days after it was reviewed. The decision and its history are kept.</li>
<li>Your date of birth and your current verification are kept while your account exists.</li>
<li>Rate-limit counters expire automatically.</li>
<li>Information stored only on your device stays there until you log out (which removes sign-in keys) or clear your browser's site data.</li>
<li>When you delete your account (from <em>Settings</em>, or by asking us), your sign-in is removed and your account is disabled. Your name, email, phone number, date of birth, ID details, verification history, QR passes, notifications, support reports, and saved checkout records are erased. Your licence plates are replaced with a meaningless code. Your past reservations are kept for the hotel's and parking facility's records, but without your name, email, phone number, or notes. Your consent records are kept to show which versions you accepted; they contain no contact details.</li>
</ul>

<h3>10. Your rights</h3>
<p>Under the Data Privacy Act you have the right:</p>
<ul>
<li>to be informed about how your personal information is processed;</li>
<li>to access it;</li>
<li>to object to processing;</li>
<li>to have it corrected;</li>
<li>to have it erased or blocked;</li>
<li>to data portability;</li>
<li>to be compensated for damages; and</li>
<li>to file a complaint with the National Privacy Commission (privacy.gov.ph).</li>
</ul>
<p>You can use some of these rights yourself in <em>Settings</em>, even if you have not accepted an updated version of these documents:</p>
<ul>
<li><strong>Correction:</strong> change your name and phone number. To correct your email address or date of birth, contact us.</li>
<li><strong>Access and portability:</strong> <em>Download my data</em> gives you a copy of what NEXORA stores about your account, in JSON, a common machine-readable format.</li>
<li><strong>Erasure:</strong> <em>Delete my account</em>, as described in section 9.</li>
</ul>
<p>For anything else, email ${contact} from the address on your account, so we can confirm it is you. We will respond within [TO BE COMPLETED BY OPERATOR: response period].</p>
<p>The Service is provided under the Terms of Service. If you no longer accept them, you can stop using the Service and delete your account.</p>

<h3>11. Cookies, local storage, and sessions</h3>
<ul>
<li>NEXORA does not set its own cookies and uses no analytics or advertising trackers.</li>
<li>To keep you signed in and remember your preferences, it uses your browser's local storage and session storage, as described in section 3.</li>
<li>Logging out removes your sign-in keys from the browser.</li>
<li>Embedded third-party content (Google Maps and Google Fonts) may set or read its own cookies.</li>
</ul>

<h3>12. Children</h3>
<p>NEXORA accounts are only for people aged 18 or over. Sign-up asks for your date of birth and refuses anyone under 18. If an existing account's date of birth shows the holder is under 18, booking is not available on it, and the holder or a parent or guardian can ask us to delete it at ${contact}.</p>

<h3>13. Changes to this policy</h3>
<p>Each version of this policy has a version number and an effective date. If we change it in a way that matters, we will raise the version number and ask you to review and acknowledge the new version before you continue using your account. We keep a record of each version you acknowledged.</p>

<h3>14. Contact and complaints</h3>
<p>Privacy questions, requests, and complaints: ${contact}.</p>
<p>Data Protection Officer: [TO BE COMPLETED BY OPERATOR].</p>
<p>If you are not satisfied with our response, you may contact the National Privacy Commission of the Philippines.</p>
`;

  window.NEXORA_LEGAL = Object.freeze({
    contactEmail: CONTACT_EMAIL,
    documents: Object.freeze([
      Object.freeze({
        type: "terms",
        title: "Terms of Service",
        shortTitle: "Terms",
        version: "1.2",
        effective: "30 October 2026",
        html: terms,
      }),
      Object.freeze({
        type: "privacy",
        title: "Privacy Policy",
        shortTitle: "Privacy",
        version: "1.2",
        effective: "30 October 2026",
        html: privacy,
      }),
    ]),
  });
})();
