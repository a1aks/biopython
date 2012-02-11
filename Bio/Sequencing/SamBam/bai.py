# Copyright 2012 by Peter Cock.
# All rights reserved.
# This code is part of the Biopython distribution and governed by its
# license.  Please see the LICENSE file that should have been included
# as part of this package.
r"""Fairly low level API for working with SAM/BAM index files (BAI).

This is intended to be written in Pure Python (so that it will work
under PyPy, Jython, etc) but will attempt to follow the pysam API
somewhat (which is a wrapper for the samtools C API).
"""

import struct

_BAM_MAX_BIN =  37450 # (8^6-1)/7+1

def _test_bai(handle):
    """Test function for loading a BAI file.

    >>> handle = open("SamBam/ex1.bam.bai", "rb")
    >>> _test_bai(handle)
    2 references
    1 bins, 1 linear baby-bins, 1446 reads mapped, 18 unmapped
    1 bins, 1 linear baby-bins, 1789 reads mapped, 17 unmapped
    0 unmapped reads
    >>> handle.close()

    >>> handle = open("SamBam/tags.bam.bai", "rb")
    >>> _test_bai(handle)
    2 references
    1 bins, 1 linear baby-bins, 417 reads mapped, 0 unmapped
    0 bins, 0 linear baby-bins, ? reads mapped, ? unmapped
    0 unmapped reads
    >>> handle.close()

    >>> handle = open("SamBam/bins.bam.bai", "rb")
    >>> _test_bai(handle)
    3 references
    1 bins, 1 linear baby-bins, 152 reads mapped, 0 unmapped
    5 bins, 4 linear baby-bins, 397 reads mapped, 0 unmapped
    73 bins, 64 linear baby-bins, 5153 reads mapped, 0 unmapped
    12 unmapped reads
    >>> handle.close()

    """
    indexes, unmapped = _load_bai(handle)
    print "%i references" % len(indexes)
    for chunks, linear, mapped, ref_unmapped, u_start, u_end in indexes:
        if mapped is None:
            assert ref_unmapped is None
            print "%i bins, %i linear baby-bins, ? reads mapped, ? unmapped" \
                  % (len(chunks), len(linear))
        else:
            print "%i bins, %i linear baby-bins, %i reads mapped, %i unmapped" \
                  % (len(chunks), len(linear), mapped, ref_unmapped)
    if unmapped is None:
        print "Index missing unmapped reads count"
    else:
        print "%i unmapped reads" % unmapped

def _load_bai(handle):
    indexes = []
    magic = handle.read(4)
    if magic != "BAI" + chr(1):
        raise ValueError("BAM index files should start 'BAI\1', not %r" \
                         % magic)
    assert 4 == struct.calcsize("<i")
    assert 8 == struct.calcsize("<Q")
    data = handle.read(4)
    n_ref = struct.unpack("<i", data)[0]
    #print "%i references" % n_ref
    for n in xrange(n_ref):
        indexes.append(_load_ref_index(handle))
    #This is missing on very old samtools index files,
    #and isn't in the SAM/BAM specifiction yet either.
    #This was reverse engineered vs "samtools idxstats"
    data = handle.read(8)
    if data:
        unmapped = struct.unpack("<Q", data)[0]
        #print "%i unmapped reads" % unmapped
    else:
        unmapped = None
        #print "Index missing unmapped reads count"
    data = handle.read()
    if data:
        print "%i extra bytes" % len(data)
        print repr(data)
    return indexes, unmapped

def _load_ref_index(handle):
    """Load offset chunks for bins (dict), and linear index (tuple).

    This assumes the handle is positioned at the start of the next
    reference block in the BAI file.

    It returns a dictionary for the chunks, and a list for the linear
    index. The chunk dictionary keys are bin numbers, and its values
    are lists of chunk begining and end virtual offsets. The linear
    index is just a tuple of virtual offsets (the position of the first
    aligned read in that interval) for the smallest sized bins.
    """
    mapped = None
    unmapped = None
    unmapped_start = None
    unmapped_end = None
    #First the chunks for each bin,
    n_bin = struct.unpack("<i", handle.read(4))[0]
    chunks_dict = dict()
    for b in xrange(n_bin):
        bin, chunks = struct.unpack("<ii", handle.read(8))
        if bin == _BAM_MAX_BIN:
            #At the time of writing this isn't in the SAM/BAM specification,
            #gleaned from the samtools source code instead.
            assert chunks == 2, chunks
            unmapped_start, unmapped_end = struct.unpack("<QQ", handle.read(16))
            mapped, unmapped = struct.unpack("<QQ", handle.read(16))
        else:
            chunks_list = []
            for chunk in xrange(chunks):
                #Append tuple of (chunk beginning, chunk end)
                chunks_list.append(struct.unpack("<QQ", handle.read(16)))
            chunks_dict[bin] = chunks_list
    #Now the linear index (for the smallest bins)
    n_intv = struct.unpack("<i", handle.read(4))[0]
    return chunks_dict, struct.unpack("<%iQ" % n_intv, handle.read(8*n_intv)), \
           mapped, unmapped, unmapped_start, unmapped_end

def _test():
    """Run the module's doctests (PRIVATE).

    This will try and locate the unit tests directory, and run the doctests
    from there in order that the relative paths used in the examples work.
    """
    import doctest
    import os
    if os.path.isdir(os.path.join("..", "..", "..", "Tests")):
        print "Runing doctests..."
        cur_dir = os.path.abspath(os.curdir)
        os.chdir(os.path.join("..", "..", "..", "Tests"))
        doctest.testmod()
        print "Done"
        os.chdir(cur_dir)
        del cur_dir
    elif os.path.isdir(os.path.join("Tests")):
        print "Runing doctests..."
        cur_dir = os.path.abspath(os.curdir)
        os.chdir(os.path.join("Tests"))
        doctest.testmod()
        print "Done"
        os.chdir(cur_dir)
        del cur_dir

if __name__ == "__main__":
    _test()
