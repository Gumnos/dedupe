#!/usr/bin/env python
from collections import namedtuple
import hashlib
import logging
import optparse as op
import os
import sys

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("dedupe")

SYMLINK_NEVER = "never"
SYMLINK_FALLBACK = "fallback"
SYMLINK_ALWAYS = "always"
SYMLINK_DEFAULT = SYMLINK_NEVER
SYMLINK_CHOICES = [
    SYMLINK_NEVER,
    SYMLINK_FALLBACK,
    SYMLINK_ALWAYS,
    ]

FileInfo = namedtuple("FileInfo", [
    "name",
    "dev",
    "inode",
    ])

try:
    algorithms = hashlib.algorithms_available
except AttributeError:
    algorithms = [
        algo
        for algo in dir(hashlib)
        if not (
            algo.startswith("_")
            or algo.endswith("_")
            )
        ]
algorithms = sorted(algorithms)

DEFAULT_ALGO = "sha256"
assert DEFAULT_ALGO in algorithms, "Default algorithm %s not available" % DEFAULT_ALGO

def build_parser():
    parser = op.OptionParser(
        usage="usage: %prog [options] dir1 [dir2...]",
        )
    parser.add_option("-n", "--dry-run",
        help="Don't actually do the delete/link, "
            "just list what would be linked",
        action="store_true",
        dest="dry_run",
        default=False,
        )
    parser.add_option("-q", "--quiet",
        help="Don't log which files were re-linked",
        action="store_true",
        dest="quiet",
        default=False,
        )
    parser.add_option("-r", "--recurse",
        help="Recurse into subdirectories",
        action="store_true",
        dest="recurse",
        default=False,
        )
    parser.add_option("--min-size",
        help="Minimum file-size to consider",
        dest="min_size",
        type="int",
        action="store",
        default=1,
        )
    parser.add_option("-s", "--symlink", "--sym-link",
        help="Should sym-links be used (%s)" % ", ".join(
            ("[%s]" if sym == SYMLINK_DEFAULT else "%s") % sym
            for sym
            in SYMLINK_CHOICES
            ),
        choices=SYMLINK_CHOICES,
        metavar="WHEN",
        dest="symlink",
        default=SYMLINK_DEFAULT,
        )
    parser.add_option("-a", "--algorithm",
        help="Choice of algorithm (one of %s)" % (", ".join(algorithms)),
        choices=algorithms,
        dest="algorithm",
        default=DEFAULT_ALGO,
        )
    return parser

def find_dupes(options, *dirs):
    # {size: {dev: {hash: FileInfo}}}
    # {size: {dev: FileInfo}}
    device_size_info_dict = {}

    if options.recurse:
        def walker(loc):
            for root, dirs, files in os.walk(loc):
                for fname in files:
                    yield os.path.join(root, fname)
    else:
        def walker(loc):
            for fname in os.listdir(loc):
                yield os.path.join(loc, fname)

    def get_file_hash(fname, algorithm, block_size=1024*1024):
        hasher = hashlib.new(options.algorithm)
        with open(fname, "rb") as f:
            while True:
                chunk = f.read(block_size)
                if not chunk: break
                hasher.update(chunk)
        #return hasher.digest()
        return hasher.hexdigest()

    for loc in dirs:
        for fullpath in walker(loc):
            if not os.path.isfile(fullpath):
                continue
            stat = os.stat(fullpath)
            file_size = stat.st_size
            if file_size < options.min_size:
                continue
            this_device = stat.st_dev
            this_fileinfo = FileInfo(
                fullpath,
                this_device,
                stat.st_ino,
                )
            if options.symlink == SYMLINK_NEVER:
                size_fileinfo_dict = device_size_info_dict.setdefault(
                    this_device,
                    {},
                    )
            else:
                size_fileinfo_dict = device_size_info_dict
            if file_size in size_fileinfo_dict:
                info_or_dict = size_fileinfo_dict[file_size]
                if isinstance(info_or_dict, dict):
                    # we've already hashed files for this size+dev
                    hash_to_fileinfo = info_or_dict

                    # if we've already seen a file with the same inode,
                    # no need to deduplicate it again
                    if any(fileinfo.inode == stat.st_ino
                            for fileinfo
                            in hash_to_fileinfo.itervalues()
                            ):
                        sys.stderr.write("Already deduplicated %s\n" % fullpath)
                        continue

                    this_hash = get_file_hash(fullpath, options.algorithm)
                    if this_hash in hash_to_fileinfo:
                        yield (
                            hash_to_fileinfo[this_hash],
                            this_fileinfo,
                            this_hash,
                            )
                    else:
                        size_fileinfo_dict[file_size][this_hash] = this_fileinfo

                else: # info_or_dict is just a FileInfo
                    file_info = info_or_dict
                    if file_info.inode == stat.st_ino:
                        # These are already the same file
                        continue
                    this_hash = get_file_hash(fullpath, options.algorithm)
                    # so far, we've only seen the one file
                    # thus we need to hash the original too
                    existing_file_hash = get_file_hash(
                        file_info.name,
                        options.algorithm,
                        )
                    size_fileinfo_dict[file_size] = {
                        existing_file_hash: file_info,
                        }
                    if existing_file_hash == this_hash:
                        yield (
                            file_info,
                            this_fileinfo,
                            this_hash,
                            )
                    else:
                        size_fileinfo_dict[file_size][this_hash] = this_fileinfo
            else:
                # we haven't seen this file size before
                # so just note the full path for later
                size_fileinfo_dict[file_size] =  this_fileinfo

def templink(source_path, dest_dir, name=None, prefix='tmp'):
     """Create a hard link to the given file with a unique name.
     Returns the name of the link."""
     if name is None:
        name = os.path.basename(source_path)
     i = 1
     while True:
         dest_path = os.path.join(
            dest_dir,
            "%s%s_%i" % (prefix, name, i),
            )
         try:
             os.link(source_path, dest_path)
         except OSError:
             i += 1
         else:
             break
     return dest_path

def symlink(patha, pathb, hash):
    def relsymlink(a, b):
        dest_loc = os.path.abspath(os.path.split(b)[0])
        src_loc = os.path.relpath(a, dest_loc)
        import pdb; pdb.set_trace()
        os.symlink(src_loc, b)
    return link(relsymlink, patha, pathb, hash)

def hardlink(patha, pathb, hash):
    return link(os.link, patha, pathb, hash)

def link(linkfn, patha, pathb, hash):
    # because link() can fail with an EEXIST,
    # we create a temp-name'd link file and
    # then do an atomic rename() atop the original
    # This could use tempfile.mktemp() but it has
    # been deprecated, so use the hash as a filename instead
    dest_path = os.path.split(pathb)[0]
    temp_name = os.path.join(dest_path, hash)
    linkfn(patha, temp_name)
    try:
        # this is documented as atomic
        os.rename(temp_name, pathb)
    except OSError:
        # if power is lost after the link()
        # but before the unlink()
        # we might get a leftover file
        # but that's better than losing pathb
        # by doing a delete() then link()
        os.unlink(temp_name)
        raise

def dedupe(options, *dirs):
    for fileinfo_a, fileinfo_b, hash in find_dupes(options, *dirs):
        if not options.quiet:
            log.info("%s -> %s", fileinfo_a.name, fileinfo_b.name)
        if not options.dry_run:
            try:
                if options.symlink == SYMLINK_ALWAYS:
                    symlink(fileinfo_a.name, fileinfo_b.name, hash)
                else:
                    if fileinfo_a.dev == fileinfo_b.dev:
                        # if they're on the same device
                        # hardlink them
                        hardlink(fileinfo_a.name, fileinfo_b.name, hash)
                    elif options.symlink == SYMLINK_FALLBACK:
                        # if the user wants to fallback to symlinks
                        symlink(fileinfo_a.name, fileinfo_b.name, hash)
                    else:
                        log.warn("Could not hardlink %s to %s (different devices)",
                            fileinfo_a.name,
                            fileinfo_b.name,
                            )
            except OSError:
                log.error("Could not link %s to %s\n" % (
                    fileinfo_a.name, fileinfo_b.name))

def main():
    parser = build_parser()
    options, args = parser.parse_args()
    if not args:
        parser.print_help()
        sys.exit(os.EX_USAGE)
    dedupe(options, *args)


if __name__ == "__main__":
    main()
