# Vendored for the browser tests

`axe.min.js` is [axe-core](https://github.com/dequelabs/axe-core) 4.10.3,
by Deque Systems, under the Mozilla Public License 2.0
(`axe-LICENSE.txt`). `tests/browser/test_accessibility.py` evaluates it in
each page to check WCAG 2.1 AA. It is never served by the application nor
packaged in the wheel.

To update it, take the file from the npm package, unchanged:

```bash
npm pack axe-core@<version>
tar xzf axe-core-<version>.tgz package/axe.min.js package/LICENSE
cp package/axe.min.js tests/browser/vendor/axe.min.js
cp package/LICENSE tests/browser/vendor/axe-LICENSE.txt
```
