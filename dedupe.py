import hashlib
import optparse as op
import os
import sys

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

def dedupe(options, *locations):
    pass

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
        default=0,
        )
    parser.add_option("-a", "--algorithm",
        help="Choice of algorithm (one of %s)" % (", ".join(algorithms)),
        choices=algorithms,
        dest="algorithm",
        default=DEFAULT_ALGO,
        )
    return parser

def find_dupes(options, *dirs):
    file_info_dict = {} # {dev: {size: {hash: path}}}

    if options.recurse:
        def walker(loc):
            for fname in os.listdir(loc):
                yield os.path.join(loc, fname)
    else:
        def walker(loc):
            for root, dirs, files in os.walk(loc):
                for fname in files:
                    yield os.path.join(root, fname)

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
            if not os.path.isfile(fullpath): continue
            stat = os.stat(fullpath)
            file_size = stat.st_size
            if file_size < options.min_size: continue
            current_file_device = stat.st_dev
            device_file_info_dict = file_info_dict.setdefault(
                current_file_device,
                {},
                )
            if file_size in device_file_info_dict:
                this_hash = get_file_hash(fullpath, options.algorithm)
                existing_file_info = device_file_info_dict[file_size]
                if isinstance(existing_file_info, dict):
                    # we've already hashed these files
                    if this_hash in existing_file_info:
                        yield (
                            existing_file_info[this_hash],
                            fullpath,
                            this_hash,
                            )
                    else:
                        device_file_info_dict[file_size][this_hash] = fullpath
                else:
                    # so far, we've only seen the one file
                    # thus we need to hash the original too
                    existing_file_hash = get_file_hash(
                        existing_file_info,
                        options.algorithm,
                        )
                    device_file_info_dict[file_size] = {
                        existing_file_hash: existing_file_info,
                        }
                    if existing_file_hash == this_hash:
                        yield (
                            existing_file_info,
                            fullpath,
                            this_hash,
                            )
                    else:
                        device_file_info_dict[file_size][this_hash] = fullpath
            else:
                # we haven't seen this file size before
                # so just note the full path for later
                device_file_info_dict[file_size] =  fullpath

def relink(patha, pathb, hash):
    # because link() would fail with an EEXIST,
    # we need to create a temp-name'd link file
    # and then do an atomic rename() atop the original
    dest_path = os.path.split(pathb)[0]
    temp_name = os.path.join(dest_path, hash)
    os.link(patha, temp_name)
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

def dedupe(options, *dirs):
    for full_path_a, full_path_b, hash in find_dupes(options, *dirs):
        if not options.quiet:
            print("%s -> %s" % (full_path_a, full_path_b))
        if not options.dry_run:
            try:
                relink(full_path_a, full_path_b, hash)
            except OSError:
                sys.stderr.write("Could not relink %s to %s\n" % (
                    full_path_a, full_path_b))

def main():
    parser = build_parser()
    options, args = parser.parse_args()
    if not args:
        parser.print_help()
        sys.exit(os.EX_USAGE)
    dedupe(options, *args)


if __name__ == "__main__":
    main()
