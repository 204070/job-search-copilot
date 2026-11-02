# Manatal (careers-page.com)

Load when the apply URL looks like
`https://www.careers-page.com/<board-slug>/job/<code>/apply`. The posting page
is `/job/<code>`; the form is one click further.

## What the form actually asks

The visible form is small: Full Name, Email, Phone, a required Cover Letter
textarea, a required Resume file input, one checkbox for the terms and privacy
policy, and Submit. There is no location, work-authorization, salary or
self-identification field on the default template. A board can add custom
fields, so read the page rather than assume this list.

## The DOM holds inputs that are not on the form

A naive `querySelectorAll('input,select,textarea')` returns about forty
elements: `school`, `specialization`, `started_at`, `title`, `employer`,
`salary`, `current_currency`, `expected_frequency`, and so on. Those belong to
the hidden templates behind the `Add Education` and `Add Experience` modals.
They are not visible and they are not submitted unless the modal is opened, so
they must not be filled, and they must not be recorded as questions the form
asked.

Read visibility before acting:

```js
[...document.querySelectorAll('input,select,textarea')]
  .filter(e => e.offsetParent)      // visible only
```

The AX tree from `opencli state` already shows the real form, which is the
cheaper check.

## Field ids

Each field is `#field<digits>` (`#field1171680` and so on). The digits are the
employer's own field ids: they are stable for that posting and change per
posting, not per page load. Read them from `state` at the start of the fill.

## Resume upload

`opencli upload` fails with `{"code":-32000,"message":"Not allowed"}`: the real
`input[type=file]` is styled (`custom-file-input`) behind a `Choose file`
label, so the file chooser never opens. Use the base64 embed instead, which
works on this board:

```bash
bash artifacts/scripts/embed_resume.sh <pdf> '#field<digits>' <tab-id>
```

It prints `SET name=... size=...`. Check the size against the file on disk and
read the upload zone's text back; both must show the attachment.

## Consents and human-only steps

- The terms and privacy policy checkbox is a consent. Leave it for the user and
  name it in the handover.
- Final review and Submit are the user's.

## Worked case: job #4280

A Senior Backend Engineer posting on a Manatal careers page. The board was an HR
and staffing company, so the hiring client was not the board name; that went
into the job note and the application notes.

- The visible form was the default five fields plus the consent checkbox, and
  the cover letter was required.
- The DOM carried the education, experience and salary templates, which the
  visibility filter excluded.
- `opencli upload` failed as described; `embed_resume.sh` attached the PDF and
  the zone then showed the filename.
- Left for the user: the consent checkbox and Submit.
