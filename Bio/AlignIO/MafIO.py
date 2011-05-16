# Copyright 2011 by Andrew Sczesnak.  All rights reserved.
# Revisions Copyright 2011 by Peter Cock.  All rights reserved.
#
# This code is part of the Biopython distribution and governed by its
# license.  Please see the LICENSE file that should have been included
# as part of this package.
"""Bio.AlignIO support for the "maf" multiple alignment format.

You are expected to use this module via the Bio.AlignIO functions(or the
Bio.SeqIO functions if you want to work directly with the gapped sequences).

"""
from Bio.Seq import Seq
from Bio.SeqRecord import SeqRecord
from Bio.Align.Generic import Alignment
from Bio.Align import MultipleSeqAlignment
from Interfaces import AlignmentIterator, SequentialAlignmentWriter

"""
from Bio import AlignIO
a = AlignIO.parse("/comp_sync/data/foreign/ucsc/20100921_multiz30way/chr10.maf", "maf")

for b in a:
    AlignIO.write(b, "/tmp/tmp1", "maf", True)

"""

class MafWriter(SequentialAlignmentWriter):
    def write_header(self):
        self.handle.write ("##maf version=1 scoring=none\n")
        self.handle.write ("# generated by Biopython\n\n")

    def _write_record (self, record):
        this_line = ["s"]

        try:
            this_src = record.annotations["src"]
        except (AttributeError, KeyError):
            this_src = record.id

        #In the MAF file format, spaces are not allowed in the id
        this_src = this_src.replace(" ","_")

        try:
            this_start = record.annotations["start"]
        except (AttributeError, KeyError):
            this_start = 0

        try:
            this_size = record.annotations["size"]
        except (AttributeError, KeyError):
            this_size = len (record)

        try:
            this_strand = record.annotations["strand"]
        except(AttributeError, KeyError):
            this_strand = "+"

        try:
            this_srcSize = record.annotations["srcSize"]
        except(AttributeError, KeyError):
            this_srcSize = 0

        this_line.append("%-40s" % (this_src,))
        this_line.append("%15s" % (this_start,))
        this_line.append("%5s" % (this_size,))
        this_line.append(this_strand)
        this_line.append("%15s" % (this_srcSize,))
        this_line.append(str(record.seq))

        self.handle.write(" ".join(this_line),)
        self.handle.write("\n")

    def write_alignment(self, alignment):

        if not isinstance(alignment, Alignment):
            raise TypeError("Expected an alignment object")
        
        if len(set([len(x) for x in alignment])) > 1:
            raise ValueError("Sequences must all be the same length")

        all_ids = [x.id for x in alignment]

        if len(all_ids) != len(set(all_ids)):
            raise ValueError("Identifiers in each MultipleSeqAlignment must be unique")

        # for this format, there really should be an 'annotations' dict at the level
        # of the alignment object, not just SeqRecords
        try:
            this_anno = " ".join(["%s=%s" % (x, y) for x, y in alignment.annotations.iteritems()])
        except AttributeError:
            this_anno = "score=0.00"

        self.handle.write("a %s\n" % (this_anno,))

        recs_out = 0

        for record in alignment:
            self._write_record(record)

            recs_out += 1

        self.handle.write("\n")

        return recs_out

class MafIterator(AlignmentIterator):
    def _fetch_bundle(self):
        this_bundle = []

        # iterate through file, capture a bundle of lines
        line = self.handle.readline()

        while line:
            if line.startswith("a"):
                if len(this_bundle) > 0:
                    # rewind the pointer so we don't lose this line next time
                    self.handle.seek(self.handle.tell() - len(line))
                    break

                this_bundle = [line]
            elif line.startswith("#") or not line.strip():
                pass
            else:
                this_bundle.append(line)

            line = self.handle.readline()

        return this_bundle

    @staticmethod
    def _parse_bundle(bundle):
        # "s" line field names for making dicts
        _s_line_fields =("src", "start", "size", "strand", "srcSize", "text")

        # stores the "a" line and all "s" lines
        bundle_ids = []
        bundle_s_lines = {}
        bundle_a_line = None

        # parse everything
        for line in bundle:
            if line.startswith("s"):
                line_split = line.strip().split()

                if len(line_split) > 7:
                    raise ValueError("Error parsing alignment - 's' line with > 7 fields")
                #Cannot assume the identifier is database.chromosome
                #idn = line_split[1].split(".", 1)[0]
                idn = line_split[1]
                if idn in bundle_ids:
                    raise ValueError("Error parsing alignment - duplicate ID in one bundle")
                bundle_ids.append(idn)
                bundle_s_lines[idn] = dict(zip(_s_line_fields, line_split[1:]))
            elif line.startswith("a"):
                if bundle_a_line != None:
                    raise ValueError("Error parsing alignment - multiple 'a' lines in one bundle")

                bundle_a_line = dict([x.split("=") for x in line.strip().split()[1:]])

            ##TODO
            # Parse 'i' 'q' 'e' lines--they aren't in the MAF spec, but are in
            # files produced by multiz, apparently

        # check that all sequences are the same length
        if len(set([len(x["text"]) for x in bundle_s_lines.values()])) > 1:
            raise ValueError("Error parsing alignment - sequences of different length?")

        return(bundle_a_line, bundle_s_lines, bundle_ids)

    def _build_alignment(self, parsed_bundle):
        # build the multiple alignment object
        alignment = MultipleSeqAlignment([], self.alphabet)

        alignment.annotations = parsed_bundle[0]

        for idn in parsed_bundle[2]:
            species_data = parsed_bundle[1][idn]
            this_anno = {"src": species_data["src"],
                         "start": int(species_data["start"]),
                         "srcSize": int(species_data["srcSize"]),
                         "strand": species_data["strand"],
                         "size": int(species_data["size"])}

            record = SeqRecord(Seq(species_data["text"], self.alphabet),
                                id = idn,
                                name = idn,
                                description = species_data["src"],
                                annotations = this_anno)

            alignment.append(record)

        return alignment

    def next(self):
        try:
            _ = self._header
        except AttributeError:
            line = self.handle.readline()

            if line[:15] == "##maf version=1":
                self._header = line.strip()
            elif not line:
                raise StopIteration
            else:
                raise ValueError("Did not find MAF header")

        # handoff to bundle fetcher
        this_bundle = self._fetch_bundle()

        if len(this_bundle) == 0:
            raise StopIteration

        # handoff to bundle parser
        this_parsed_bundle = self._parse_bundle(this_bundle)

        # handoff to alignment builder
        this_alignment = self._build_alignment(this_parsed_bundle)

        return this_alignment

if __name__ == "__main__":
    import tempfile
    
    # MafWriter tests
    from Bio.Alphabet import single_letter_alphabet

    # test 1 -- minimally annotated
    rec1A = SeqRecord(Seq("TAGTAGCGATATGTAGCACAGTGACAATGTAGTACA"), id = "rec1")
    rec2A = SeqRecord(Seq("TAGTAGCGATATGTAGCAAAAAAAAAATGTAGTACA"), id = "rec2")    
    
    this_tmp = tempfile.TemporaryFile("r+")
    this_mafwriter = MafWriter(this_tmp)
    
    alignment = MultipleSeqAlignment([], single_letter_alphabet)
    alignment.extend([rec1A, rec2A])

    this_mafwriter.write_file([alignment])
    this_tmp.flush()
    this_tmp.seek(0)
    
    assert this_tmp.read(4096) == \
"""##maf version=1 scoring=none
# generated by Biopython

a score=0.00
s rec1                                                   0    36 +               0 TAGTAGCGATATGTAGCACAGTGACAATGTAGTACA
s rec2                                                   0    36 +               0 TAGTAGCGATATGTAGCAAAAAAAAAATGTAGTACA

"""

    this_tmp.close()

    print "Successfully wrote records in test1!"

    # test 2 -- partially/fully annotated
    rec1B = SeqRecord(Seq("TAGTAGCGATATGCATAGTAGCGATATGCATAGTAGCGATATGCA"), id = "rec1",
                       annotations = {"src": "hg18.chr5",
                                      "start": 100000,
                                      "size": 50,
                                      "strand": "-",
                                      "srcSize": 203492342})

    rec2B = SeqRecord(Seq("TAGTA--GAGAGAGGTAGTA--GAGAGAGGTAGTA--GAGAGAGG"), id = "rec2",
                       annotations = {"src": "mm9.chr5",
                                      "start": 120000,
                                      "size": 50,
                                      "strand": "-",
                                      "srcSize": 492342})

    rec3B = SeqRecord(Seq("TAGTA--AAAAAAAAAAAA---GAGAGAGGTAGTA--GAGAGTGG"), id = "rec3",
                       annotations = {"src": "rn4.chr5",
                                      "start": 180000,
                                      "size": 50})
                                      
    this_tmp = tempfile.TemporaryFile("r+")
    this_mafwriter = MafWriter(this_tmp)
    
    alignment = MultipleSeqAlignment([], single_letter_alphabet)
    alignment.extend([rec1B, rec2B, rec3B])
    alignment.annotations = {"score": 4935893.43435,
                             "works": "excellent"}

    this_mafwriter.write_file([alignment])
    this_tmp.flush()
    this_tmp.seek(0)

    assert this_tmp.read(4096) == \
"""##maf version=1 scoring=none
# generated by Biopython

a score=4935893.43435 works=excellent
s hg18.chr5                                         100000    50 -       203492342 TAGTAGCGATATGCATAGTAGCGATATGCATAGTAGCGATATGCA
s mm9.chr5                                          120000    50 -          492342 TAGTA--GAGAGAGGTAGTA--GAGAGAGGTAGTA--GAGAGAGG
s rn4.chr5                                          180000    50 +               0 TAGTA--AAAAAAAAAAAA---GAGAGAGGTAGTA--GAGAGTGG

"""

    this_tmp.close()

    print "Successfully wrote records in test1!" 
    
    # MafIterator tests
    # taken from https://cgwb.nci.nih.gov/goldenPath/help/maf.html

    test_file1 = \
"""##maf version=1 scoring=probability
#mblastz 8.91 02-Jan-2005

a score=0.128
s human_hoxa 100  9 + 100257 ACA-TTACT
s horse_hoxa 120 10 -  98892 ACAATTGCT
s fugu_hoxa   88  8  + 90788 ACA--TGCT

a score=0.071
s human_unc 9077 8 + 10998 ACAGTATT
s horse_unc 4555 6 -  5099 ACA--ATT
s fugu_unc  4000 4 +  4038 AC----TT
"""

    this_tmp = tempfile.NamedTemporaryFile("r+")

    this_tmp.write(test_file1)
    this_tmp.flush()
    this_tmp.seek(0)

    this_mafiterator = MafIterator(this_tmp)

    first_bundle = this_mafiterator.next()
    second_bundle = this_mafiterator.next()

    this_tmp.close()

    # assertions for the first bundle
    assert len(first_bundle) == 3
    assert first_bundle.annotations["score"] == "0.128"

    assert first_bundle[0].id == "human_hoxa"
    assert str(first_bundle[0].seq) == "ACA-TTACT"
    assert first_bundle[0].annotations["src"] == "human_hoxa"
    assert first_bundle[0].annotations["start"] == 100
    assert first_bundle[0].annotations["size"] == 9
    assert first_bundle[0].annotations["strand"] == "+"
    assert first_bundle[0].annotations["srcSize"] == 100257

    assert first_bundle[1].id == "horse_hoxa"
    assert str(first_bundle[1].seq) == "ACAATTGCT"
    assert first_bundle[1].annotations["src"] == "horse_hoxa"
    assert first_bundle[1].annotations["start"] == 120
    assert first_bundle[1].annotations["size"] == 10
    assert first_bundle[1].annotations["strand"] == "-"
    assert first_bundle[1].annotations["srcSize"] == 98892

    assert first_bundle[2].id == "fugu_hoxa"
    assert str(first_bundle[2].seq) == "ACA--TGCT"
    assert first_bundle[2].annotations["src"] == "fugu_hoxa"
    assert first_bundle[2].annotations["start"] == 88
    assert first_bundle[2].annotations["size"] == 8
    assert first_bundle[2].annotations["strand"] == "+"
    assert first_bundle[2].annotations["srcSize"] == 90788


    # assertions for the second bundle
    assert len(second_bundle) == 3
    assert second_bundle.annotations["score"] == "0.071"

    assert second_bundle[0].id == "human_unc"
    assert str(second_bundle[0].seq) == "ACAGTATT"
    assert second_bundle[0].annotations["src"] == "human_unc"
    assert second_bundle[0].annotations["start"] == 9077
    assert second_bundle[0].annotations["size"] == 8
    assert second_bundle[0].annotations["strand"] == "+"
    assert second_bundle[0].annotations["srcSize"] == 10998

    assert second_bundle[1].id == "horse_unc"
    assert str(second_bundle[1].seq) == "ACA--ATT"
    assert second_bundle[1].annotations["src"] == "horse_unc"
    assert second_bundle[1].annotations["start"] == 4555
    assert second_bundle[1].annotations["size"] == 6
    assert second_bundle[1].annotations["strand"] == "-"
    assert second_bundle[1].annotations["srcSize"] == 5099

    assert second_bundle[2].id == "fugu_unc"
    assert str(second_bundle[2].seq) == "AC----TT"
    assert second_bundle[2].annotations["src"] == "fugu_unc"
    assert second_bundle[2].annotations["start"] == 4000
    assert second_bundle[2].annotations["size"] == 4
    assert second_bundle[2].annotations["strand"] == "+"
    assert second_bundle[2].annotations["srcSize"] == 4038

    print "Successfully parsed test_file1!"

    ########################################

    test_file2 = \
"""##maf version=1 scoring=tba.v8
# tba.v8(((human chimp) baboon)(mouse rat))
# multiz.v7
# maf_project.v5 _tba_right.maf3 mouse _tba_C
# single_cov2.v4 single_cov2 /dev/stdin

a score=23262.0
s hg16.chr7    27578828 38 + 158545518 AAA-GGGAATGTTAACCAAATGA---ATTGTCTCTTACGGTG
s panTro1.chr6 28741140 38 + 161576975 AAA-GGGAATGTTAACCAAATGA---ATTGTCTCTTACGGTG
s baboon         116834 38 +   4622798 AAA-GGGAATGTTAACCAAATGA---GTTGTCTCTTATGGTG
s mm4.chr6     53215344 38 + 151104725 -AATGGGAATGTTAAGCAAACGA---ATTGTCTCTCAGTGTG
s rn3.chr4     81344243 40 + 187371129 -AA-GGGGATGCTAAGCCAATGAGTTGTTGTCTCTCAATGTG

a score=5062.0
s hg16.chr7    27699739 6 + 158545518 TAAAGA
s panTro1.chr6 28862317 6 + 161576975 TAAAGA
s baboon         241163 6 +   4622798 TAAAGA
s mm4.chr6     53303881 6 + 151104725 TAAAGA
s rn3.chr4     81444246 6 + 187371129 taagga

a score=6636.0
s hg16.chr7    27707221 13 + 158545518 gcagctgaaaaca
s panTro1.chr6 28869787 13 + 161576975 gcagctgaaaaca
s baboon         249182 13 +   4622798 gcagctgaaaaca
s mm4.chr6     53310102 13 + 151104725 ACAGCTGAAAATA
"""

    this_tmp = tempfile.NamedTemporaryFile("r+")

    this_tmp.write(test_file2)
    this_tmp.flush()
    this_tmp.seek(0)

    this_mafiterator = MafIterator(this_tmp)

    first_bundle = this_mafiterator.next()
    second_bundle = this_mafiterator.next()
    third_bundle = this_mafiterator.next()

    this_tmp.close()

    # assertions for the first bundle
    assert len(first_bundle) == 5
    assert first_bundle.annotations["score"] == "23262.0"

    assert first_bundle[4].id == "rn3.chr4"
    assert str(first_bundle[4].seq) == "-AA-GGGGATGCTAAGCCAATGAGTTGTTGTCTCTCAATGTG"
    assert first_bundle[4].annotations["src"] == "rn3.chr4"
    assert first_bundle[4].annotations["start"] == 81344243
    assert first_bundle[4].annotations["size"] == 40
    assert first_bundle[4].annotations["strand"] == "+"
    assert first_bundle[4].annotations["srcSize"] == 187371129

    assert first_bundle[3].id == "mm4.chr6"
    assert str(first_bundle[3].seq) == "-AATGGGAATGTTAAGCAAACGA---ATTGTCTCTCAGTGTG"
    assert first_bundle[3].annotations["src"] == "mm4.chr6"
    assert first_bundle[3].annotations["start"] == 53215344
    assert first_bundle[3].annotations["size"] == 38
    assert first_bundle[3].annotations["strand"] == "+"
    assert first_bundle[3].annotations["srcSize"] == 151104725

    assert first_bundle[2].id == "baboon"
    assert str(first_bundle[2].seq) == "AAA-GGGAATGTTAACCAAATGA---GTTGTCTCTTATGGTG"
    assert first_bundle[2].annotations["src"] == "baboon"
    assert first_bundle[2].annotations["start"] == 116834
    assert first_bundle[2].annotations["size"] == 38
    assert first_bundle[2].annotations["strand"] == "+"
    assert first_bundle[2].annotations["srcSize"] == 4622798

    assert first_bundle[1].id == "panTro1.chr6"
    assert str(first_bundle[1].seq) == "AAA-GGGAATGTTAACCAAATGA---ATTGTCTCTTACGGTG"
    assert first_bundle[1].annotations["src"] == "panTro1.chr6"
    assert first_bundle[1].annotations["start"] == 28741140
    assert first_bundle[1].annotations["size"] == 38
    assert first_bundle[1].annotations["strand"] == "+"
    assert first_bundle[1].annotations["srcSize"] == 161576975

    assert first_bundle[0].id == "hg16.chr7"
    assert str(first_bundle[0].seq) == "AAA-GGGAATGTTAACCAAATGA---ATTGTCTCTTACGGTG"
    assert first_bundle[0].annotations["src"] == "hg16.chr7"
    assert first_bundle[0].annotations["start"] == 27578828
    assert first_bundle[0].annotations["size"] == 38
    assert first_bundle[0].annotations["strand"] == "+"
    assert first_bundle[0].annotations["srcSize"] == 158545518

    # assertions for the second bundle
    assert len(second_bundle) == 5
    assert second_bundle.annotations["score"] == "5062.0"

    assert second_bundle[4].id == "rn3.chr4"
    assert str(second_bundle[4].seq) == "taagga"
    assert second_bundle[4].annotations["src"] == "rn3.chr4"
    assert second_bundle[4].annotations["start"] == 81444246
    assert second_bundle[4].annotations["size"] == 6
    assert second_bundle[4].annotations["strand"] == "+"
    assert second_bundle[4].annotations["srcSize"] == 187371129

    assert second_bundle[3].id == "mm4.chr6"
    assert str(second_bundle[3].seq) == "TAAAGA"
    assert second_bundle[3].annotations["src"] == "mm4.chr6"
    assert second_bundle[3].annotations["start"] == 53303881
    assert second_bundle[3].annotations["size"] == 6
    assert second_bundle[3].annotations["strand"] == "+"
    assert second_bundle[3].annotations["srcSize"] == 151104725

    assert second_bundle[2].id == "baboon"
    assert str(second_bundle[2].seq) == "TAAAGA"
    assert second_bundle[2].annotations["src"] == "baboon"
    assert second_bundle[2].annotations["start"] == 241163
    assert second_bundle[2].annotations["size"] == 6
    assert second_bundle[2].annotations["strand"] == "+"
    assert second_bundle[2].annotations["srcSize"] == 4622798

    assert second_bundle[1].id == "panTro1.chr6"
    assert str(second_bundle[1].seq) == "TAAAGA"
    assert second_bundle[1].annotations["src"] == "panTro1.chr6"
    assert second_bundle[1].annotations["start"] == 28862317
    assert second_bundle[1].annotations["size"] == 6
    assert second_bundle[1].annotations["strand"] == "+"
    assert second_bundle[1].annotations["srcSize"] == 161576975

    assert second_bundle[0].id == "hg16.chr7"
    assert str(second_bundle[0].seq) == "TAAAGA"
    assert second_bundle[0].annotations["src"] == "hg16.chr7"
    assert second_bundle[0].annotations["start"] == 27699739
    assert second_bundle[0].annotations["size"] == 6
    assert second_bundle[0].annotations["strand"] == "+"
    assert second_bundle[0].annotations["srcSize"] == 158545518
    
    # assertions for the third bundle
    assert len(third_bundle) == 4
    assert third_bundle.annotations["score"] == "6636.0"

    assert third_bundle[3].id == "mm4.chr6"
    assert str(third_bundle[3].seq) == "ACAGCTGAAAATA"
    assert third_bundle[3].annotations["src"] == "mm4.chr6"
    assert third_bundle[3].annotations["start"] == 53310102
    assert third_bundle[3].annotations["size"] == 13
    assert third_bundle[3].annotations["strand"] == "+"
    assert third_bundle[3].annotations["srcSize"] == 151104725

    assert third_bundle[2].id == "baboon"
    assert str(third_bundle[2].seq) == "gcagctgaaaaca"
    assert third_bundle[2].annotations["src"] == "baboon"
    assert third_bundle[2].annotations["start"] == 249182
    assert third_bundle[2].annotations["size"] == 13
    assert third_bundle[2].annotations["strand"] == "+"
    assert third_bundle[2].annotations["srcSize"] == 4622798

    assert third_bundle[1].id == "panTro1.chr6"
    assert str(third_bundle[1].seq) == "gcagctgaaaaca"
    assert third_bundle[1].annotations["src"] == "panTro1.chr6"
    assert third_bundle[1].annotations["start"] == 28869787
    assert third_bundle[1].annotations["size"] == 13
    assert third_bundle[1].annotations["strand"] == "+"
    assert third_bundle[1].annotations["srcSize"] == 161576975

    assert third_bundle[0].id == "hg16.chr7"
    assert str(third_bundle[0].seq) == "gcagctgaaaaca"
    assert third_bundle[0].annotations["src"] == "hg16.chr7"
    assert third_bundle[0].annotations["start"] == 27707221
    assert third_bundle[0].annotations["size"] == 13
    assert third_bundle[0].annotations["strand"] == "+"
    assert third_bundle[0].annotations["srcSize"] == 158545518

    print "Successfully parsed test_file2!"
