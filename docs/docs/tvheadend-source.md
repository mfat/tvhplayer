# Built-in Tvheadend source

The deb, rpm, and Flatpak packages build the built-in server from the `tvhplayer` branch of TVHplayer's fork, [mfat/tvheadend](https://github.com/mfat/tvheadend). That branch is an upstream commit with fixes on top that upstream has not merged yet. Each fix also goes to [tvheadend/tvheadend](https://github.com/tvheadend/tvheadend) as a pull request. The fork lets a fix ship before upstream merges it.

## Pins

Three files name the commit, and `tests/test_packaging_pins.py` fails when they disagree:

| File | Used by | Fields |
|---|---|---|
| `packaging/tvheadend/pins.env` | deb (`build-tvheadend.sh`) | `TVHEADEND_REPO`, `TVHEADEND_COMMIT`, `TVHEADEND_SHA256`, `TVHEADEND_VERSION` |
| `rpm.spec` | rpm | `tvh_repo`, `tvh_commit`, `tvh_version` |
| `io.github.mfat.tvhplayer.yml` | Flatpak | the `tvheadend` module's `git` source: `url`, `commit` |

The deb and rpm builds download `<repo>/archive/<commit>.tar.gz`, and the deb build checks it against `TVHEADEND_SHA256`. The Flatpak clones the repository, so `git describe` needs the upstream `v4.3` tag on the fork. An archive has no `.git`, so `TVHEADEND_VERSION` is what `git describe --tags --long --match 'v*'` prints for the commit, with `~g` in place of `-g`. rpm writes it as `4.3^N.gHASH`.

## Fixes on the branch

| Commit | Fix | Upstream |
|---|---|---|
| `ca801fa96` | iptv: start quickly with tens of thousands of muxes | [#2366](https://github.com/tvheadend/tvheadend/pull/2366) |
| `cc1b558b5` | iptv, notify: keep working when an allocation fails (review on #2366) | [#2366](https://github.com/tvheadend/tvheadend/pull/2366) |
| `e507a3ca2` | idnode: map a large bouquet to channels quickly | not yet |
| `afa7ce08d` | idnode: save pending changes before services are torn down | not yet |
| `40e88d4ce` | htsp: send a tag's members once after many channels join it | not yet |

Base: upstream `51ec612fa`.

## Changing the pin

1. In a Tvheadend checkout with the fork as a remote, commit the fix on top of the `tvhplayer` branch. To move to a newer upstream, rebase the branch onto it. Drop the fixes upstream has merged.
2. Push the branch and a tag for the new commit, `tvhplayer-YYYY-MM-DD`. Never delete a tag or force-push over a commit that a released package pins. GitHub can stop serving the archive of a commit that no branch or tag points to.
3. Update the three files. Get the version from `git describe --tags --long --match 'v*' <commit>` (without `--match`, the `tvhplayer-` tags win) and the checksum from `curl -sL <repo>/archive/<commit>.tar.gz | sha256sum`.
4. Run `tests/test_packaging_pins.py`, then `packaging/tvheadend/build-tvheadend.sh fetch` and `build` to confirm the archive downloads, verifies, and compiles.
5. Update the table above.

When the branch has no fixes left on top of upstream, point all three files back to `https://github.com/tvheadend/tvheadend` at that upstream commit.
