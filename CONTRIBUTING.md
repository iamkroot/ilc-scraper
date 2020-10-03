# Contribution Guidelines

## Creating an Issue
*   Found a bug? Want a feature added? Looking for help understanding the code? Feel free to create an [issue](https://github.com/iamkroot/ilc-scraper/issues/new/choose).
*   But first, make sure you have read through the [README](https://github.com/iamkroot/ilc-scraper).
*   Search the existing [list](https://github.com/iamkroot/ilc-scraper/issues?q=is%3Aissue) of open (or closed) issues for duplicates.
*   When creating a bug report, ensure that you have attached the relevant portions of the output, including the error traceback, if any.

## Pull Request flow
### Before working on a PR
If you wish to contribute by submitting code, please first discuss the change you wish to make by creating an issue (if not already present). That way, we can minimize wasted effort on both sides.

### How to make a PR
1. Fork this repository in your account.
2. Clone it on your local machine.
3. Add a new remote using `git remote add upstream https://github.com/iamkroot/ilc-scraper.git`.
4. Create a new feature branch with `git checkout -b my-feature`.
5. Make your changes.
6. Commit your changes (See [Guidelines](#commit-message-guidelines)).
7. Rebase your commits with `upstream/master`:
    - `git checkout master`
    - `git fetch upstream master`
    - `git reset --hard FETCH_HEAD`
    - `git checkout my-feature`
    - `git rebase master`
8. Resolve any merge conflicts, and then push the branch with `git push origin my-feature`.
9. Create a Pull Request detailing the changes you made and wait for review/merge.

## Commit Message Guidelines
Follow [this](https://www.slideshare.net/TarinGamberini/commit-messages-goodpractices) cute guide.

TL;DR, the commit message:
*   is written in the imperative (e.g., "Fix ...", "Add ...")
*   is kept short, while concisely explaining what the commit does.
*   is clear about what part of the code is affected -- often by prefixing with the name of the subsystem and a colon, like "notifier: ..." or "cli: ...".
*   is a complete sentence, *not* ending with a period.

...and the commmit body: 
*   if needed, explains the rationale behind the change.
*   ends with the ID of the linked issue (e.g., "Closes [#26](https://github.com/iamkroot/ilc-scraper/issues/26)", "Fixes [#19](https://github.com/iamkroot/trakt-scrobbler/issues/19)". 'Fixes' is used for bugs, 'Closes' for features)
