# dedupe
Deduplicate files within a given list of directories by keeping one copy
and making the rest links.

This should happen atomically on Linux/Unix platforms, but due to
limitations in the Python/Windows layers, may not be atomic on Windows.
There may also be issues on Windows regarding the use of symlinks.

```
Usage: dedupe.py [options] dir1 [dir2...]

Options:
  -h, --help            show this help message and exit
  -n, --dry-run         Don't actually do the delete/link, just list what
                        would be linked
  -q, --quiet           Don't log which files were re-linked
  -r, --recurse         Recurse into subdirectories
  --min-size=MIN_SIZE   Minimum file-size to consider
  -s WHEN, --symlink=WHEN, --sym-link=WHEN
                        Should sym-links be used ([never], fallback, always)
  -a ALGORITHM, --algorithm=ALGORITHM
                        Choice of algorithm (one of DSA, DSA-SHA, MD4, MD5,
                        RIPEMD160, SHA, SHA1, SHA224, SHA256, SHA384, SHA512,
                        dsaEncryption, dsaWithSHA, ecdsa-with-SHA1, md4, md5,
                        ripemd160, sha, sha1, sha224, sha256, sha384, sha512,
                        whirlpool)
```

Originally I had tried out
[a similar dedupe tool](https://github.com/jeek/dedupe)
by @jeek but it had a few issues:

- it hashed every file, not just the ones that were suspected of being
  duplicates.  So on my low-end hosting service, `jailshell` would kill
  off the process because it was taking too long (or maybe doing too
  much I/O in one command). With my 3.2GB of photos,  @jeek's would
  time-out after minutes where this one ran in seconds.

- it didn't have the option of doing a dry-run to see which files would be
  deduplicated, without actually performing the deduplication

- it didn't detect whether deduplicated files were on different
  devices/mount-points and attempts to `link()` would fail in those
  cases

- it didn't support doing sym-links

Thus, this utility was born.  Basically, this should behave as the same
utility, but faster and with a few more features.
