# Copyright 2009-2010 by Peter Cock.  All rights reserved.
# This code is part of the Biopython distribution and governed by its
# license.  Please see the LICENSE file that should have been included
# as part of this package.
"""Dictionary like indexing of sequence files (PRIVATE).

You are not expected to access this module, or any of its code, directly. This
is all handled internally by the Bio.SeqIO.index(...) function which is the
public interface for this functionality.

The basic idea is that we scan over a sequence file, looking for new record
markers. We then try and extract the string that Bio.SeqIO.parse/read would
use as the record id, ideally without actually parsing the full record. We
then use an SQLite3 database to record the file offset for the record start
against the record id.

Note that this means full parsing is on demand, so any invalid or problem
record may not trigger an exception until it is accessed. This is by design.
"""

import os
import re
from sqlite3 import dbapi2 as _sqlite
from sqlite3 import IntegrityError as _IntegrityError
import UserDict

from Bio import SeqIO
from Bio import Alphabet

class _IndexedSeqFileDict(UserDict.DictMixin):
    """Read only dictionary interface to a sequential sequence file.

    Scans the file and notes the record identifies (keys) and associated
    offsets into the file.  When accessing a record, reads the file to
    access entries as SeqRecord objects using Bio.SeqIO for parsing them.

    By default, the record identifiers and their offsets are held in
    memory, but if an index_filename is given this will be used for an
    SQLite database.

    Note - as with the Bio.SeqIO.to_dict() function, duplicate keys
    (record identifiers by default) are not allowed. If this happens,
    a ValueError exception is raised.

    By default the SeqRecord's id string is used as the dictionary
    key. This can be changed by suppling an optional key_function,
    a callback function which will be given the record id and must
    return the desired key. For example, this allows you to parse
    NCBI style FASTA identifiers, and extract the GI number to use
    as the dictionary key.

    Note that this dictionary is essentially read only. You cannot
    add or change values, pop values, nor clear the dictionary.
    """
    def __init__(self, filename, index_filename, format, alphabet,
                 key_function):
        #Use key_function=None for default value
        if format in SeqIO._BinaryFormats:
            mode = "rb"
        else:
            mode = "rU"
        self._handle = open(filename, mode)
        self._alphabet = alphabet
        self._format = format
        self._key_function = key_function
        self._index_filename = index_filename
        self._setup()
        if not index_filename:
            #Hold the offsets in memory
            self._offsets = {}
            self._build()
            #TODO - Need to add a duplicate key check
        elif os.path.isfile(index_filename):
            #Reuse the index
            self._offsets = _SqliteOffsetDict(index_filename)
            #Very basic test of the index
            #Using first and last entries alphabetically since there is an
            #index on the key column. I would like to use the first and last
            #entries in the file, but would be slow without an index on the
            #offset column which we don't otherwise need.
            if len(self):
                key = str(self._offsets._con.execute("SELECT key FROM data ORDER BY key ASC LIMIT 1;").fetchone()[0])
                try:
                    record = self[key]
                    del key, record
                except Exception, err:
                    raise ValueError("Is %s an out of date index database? %s" \
                                     % (index_filename, err))
                key = str(self._offsets._con.execute("SELECT key FROM data ORDER BY key DESC LIMIT 1;").fetchone()[0])
                try:
                    record = self[key]
                    del key, record
                except Exception, err:
                    raise ValueError("Is %s an out of date index database? %s" \
                                     % (index_filename, err))
        else :
            #Create the index file
            self._offsets = _SqliteOffsetDict(index_filename)

            import time
            start = time.time()
            self._build()
            print "Loading offsets done in %0.1fs" % (time.time()-start)

            start = time.time()
            self._offsets._finish() #build the index on the key column
            print "Indexing offsets done in %0.1fs" % (time.time()-start)
    
    def _setup(self):
        """Parse the header etc if required (PRIVATE)."""
        pass
    
    def _build(self):
        """Actually scan the file identifying records and offsets (PRIVATE)."""
        pass
    
    def _flush(self):
        """Flush an pending commits to the DB (PRIVATE)."""
        try:
            self._offsets._flush()
        except AttributeError:
            pass

    def __repr__(self):
        return "SeqIO.index('%s', '%s', alphabet=%s, key_function=%s, mode=%s, index_filename=%s)" \
               % (self._handle.name, self._format,
                  repr(self._alphabet), self._key_function,
                  self._handle.mode, self._index_filename)

    def __str__(self):
        if self:
            key = self._offsets.next()
            return "{%s : SeqRecord(...), ...}" % repr(key)
        else:
            return "{}"

    def __contains__(self, key) :
        return key in self._offsets
        
    def _record_key(self, identifier, seek_position):
        """Used by subclasses to record file offsets for identifiers (PRIVATE).

        This will apply the key_function (if given) to map the record id
        string to the desired key.

        This will raise a ValueError if a key (record id string) occurs
        more than once.
        """
        if self._key_function:
            key = self._key_function(identifier)
        else:
            key = identifier
        self._offsets[key] = seek_position

    def _get_offset(self, key) :
        #Separate method to help ease complex subclassing like SFF
        return self._offsets[key]

    def __len__(self):
        """How many records are there?"""
        return len(self._offsets)

    def keys(self) :
        """Return a list of all the keys (SeqRecord identifiers)."""
        #TODO - Stick a warning in here for large lists? Or just refuse?
        return self._offsets.keys()

    def values(self):
        """Would be a list of the SeqRecord objects, but not implemented.

        In general you can be indexing very very large files, with millions
        of sequences. Loading all these into memory at once as SeqRecord
        objects would (probably) use up all the RAM. Therefore we simply
        don't support this dictionary method.
        """
        raise NotImplementedError("Due to memory concerns, when indexing a "
                                  "sequence file you cannot access all the "
                                  "records at once.")

    def items(self):
        """Would be a list of the (key, SeqRecord) tuples, but not implemented.

        In general you can be indexing very very large files, with millions
        of sequences. Loading all these into memory at once as SeqRecord
        objects would (probably) use up all the RAM. Therefore we simply
        don't support this dictionary method.
        """
        raise NotImplementedError("Due to memory concerns, when indexing a "
                                  "sequence file you cannot access all the "
                                  "records at once.")

    def iteritems(self):
        """Iterate over the (key, SeqRecord) items."""
        for key in self.__iter__():
            yield key, self.__getitem__(key)

    def __getitem__(self, key):
        """x.__getitem__(y) <==> x[y]"""
        #For non-trivial file formats this must be over-ridden in the subclass
        handle = self._handle
        handle.seek(self._get_offset(key))
        record = SeqIO.parse(handle, self._format, self._alphabet).next()
        if self._key_function:
            assert self._key_function(record.id) == key, \
                   "Requested key %s, found record.id %s which has key %s" \
                   % (repr(key), repr(record.id),
                      repr(self._key_function(record.id)))
        else:
            assert record.id == key, \
                   "Requested key %s, found record.id %s" \
                   % (repr(key), repr(record.id))
        return record

    def get(self, k, d=None):
        """D.get(k[,d]) -> D[k] if k in D, else d.  d defaults to None."""
        try:
            return self.__getitem__(k)
        except KeyError:
            return d

    def get_raw(self, key):
        """Similar to the get method, but returns the record as a raw string.

        If the key is not found, a KeyError exception is raised.

        NOTE - This functionality is not supported for every file format.
        """
        #Should be done by each sub-class (if possible)
        raise NotImplementedError("Not available for this file format.")

    def __setitem__(self, key, value):
        """Would allow setting or replacing records, but not implemented."""
        raise NotImplementedError("A sequence file index is read only.")
    
    def update(self, **kwargs):
        """Would allow adding more values, but not implemented."""
        raise NotImplementedError("A sequence file index is read only.")
    
    def pop(self, key, default=None):
        """Would remove specified record, but not implemented."""
        raise NotImplementedError("A sequence file index is read only.")
    
    def popitem(self):
        """Would remove and return a SeqRecord, but not implemented."""
        raise NotImplementedError("A sequence file index is read only.")
    
    def clear(self):
        """Would clear dictionary, but not implemented."""
        raise NotImplementedError("A sequence file index is read only.")

    def fromkeys(self, keys, value=None):
        """A dictionary method which we don't implement."""
        raise NotImplementedError("A sequence file index doesn't "
                                  "support this.")

    def copy(self):
        """A dictionary method which we don't implement."""
        raise NotImplementedError("A sequence file index doesn't "
                                  "support this.")

#Based in part on this recipe for implementing a dictionary on top of SQLite:
#http://sebsauvage.net/python/snyppets/index.html#dbdict
#TODO - What about closing the connection nicely?
class _SqliteOffsetDict(UserDict.DictMixin):
    """Simple dictionary like object based on SQLite (PRIVATE)."""
    def __init__(self, index_filename):
        #Use key_function=None for default value
        self._pending = []
        if os.path.isfile(index_filename):
            #Reuse the index
            self._con = _sqlite.connect(index_filename)
        else :
            #Create the index
            #Use isolation_level=None to handle transactions explicitly
            self._con = _sqlite.connect(index_filename, isolation_level=None)
            #Don't index the key column until the end (faster)
            #self._con.execute("CREATE TABLE data (key TEXT PRIMARY KEY, "
            #                  "offset INTEGER);")
            self._con.execute("CREATE TABLE data (key TEXT, offset INTEGER);")
            #self._con.execute("PRAGMA synchronous = off;")
            self._con.commit()
    
    def _flush(self):
        #print "Flushing %i values" % len(self._pending)
        if self._pending:
            execute = self._con.execute
            execute("BEGIN TRANSACTION;")
            for key, offset in self._pending:
                try:
                    execute("INSERT INTO data (key,offset) VALUES (?,?);",
                            (key, offset))
                except _IntegrityError: #column key is not unique
                    #assert key in self
                    raise ValueError("Duplicate key %s (offset %i)" \
                                     % (repr(key), offset))
            execute("COMMIT TRANSACTION;")
            self._pending = []
        self._con.commit()
    
    def _finish(self):
        """Flush any pending commits, and build the index. May raise KeyError."""
        self._flush()
        try:
            self._con.execute("CREATE UNIQUE INDEX IF NOT EXISTS "
                              "key_index ON data(key);")
        except _IntegrityError, err:
            raise ValueError("Duplicate key? %s" % err)
        self._con.commit()
    
    def __contains__(self, key) :
        return bool(self._con.execute("SELECT key FROM data WHERE key=?",(key,)).fetchone())
        
    def __setitem__(self, key, offset):
        """
        try:
            self._con.execute("INSERT INTO data (key,offset) VALUES (?,?);",
                              (key, offset))
        except _IntegrityError: #column key is not unique
            assert key in self
            raise ValueError("Duplicate key %s (offset %i)" \
                             % (repr(key), offset))
        """
        self._pending.append((key, offset))
        if len(self._pending) >= 10000:
            self._flush()

    def __getitem__(self, key) :
        row = self._con.execute("SELECT offset FROM data WHERE key=?;",(key,)).fetchone()
        if not row: raise KeyError
        return row[0]

    def __len__(self):
        """How many records are there?"""
        return self._con.execute("SELECT COUNT(key) FROM data;").fetchone()[0]

    def keys(self) :
        """Return a list of all the keys (SeqRecord identifiers)."""
        #TODO - Stick a warning in here for large lists? Or just refuse?
        return [str(row[0]) for row in \
                self._con.execute("SELECT key FROM data;").fetchall()]

    def values(self):
        """Would be a list of the offsets (integers)."""
        return [row[0] for row in \
                self._con.execute("SELECT offset FROM data;").fetchall()]

    def items(self):
        """List of (key, offset) tuples."""
        return [(str(row[0]),row[1]) for row in \
                self._con.execute("SELECT key, offset FROM data;").fetchall()]

    def iteritems(self):
        """Iterate over the (key, SeqRecord) items."""
        for key in self.__iter__():
            yield key, self.__getitem__(key)

    def get(self, k, d=None):
        """D.get(k[,d]) -> D[k] if k in D, else d.  d defaults to None."""
        try:
            return self.__getitem__(k)
        except KeyError:
            return d

    def update(self, **kwargs):
        """Would allow adding more values, but not implemented."""
        raise NotImplementedError()
    
    def pop(self, key, default=None):
        """Would remove specified record, but not implemented."""
        raise NotImplementedError()
    
    def popitem(self):
        """Would remove and return a SeqRecord, but not implemented."""
        raise NotImplementedError()
    
    def clear(self):
        """Would clear dictionary, but not implemented."""
        raise NotImplementedError()

    def fromkeys(self, keys, value=None):
        """A dictionary method which we don't implement."""
        raise NotImplementedError()

    def copy(self):
        """A dictionary method which we don't implement."""
        raise NotImplementedError()


####################
# Special indexers #
####################

# Anything where the records cannot be read simply by parsing from
# the record start. For example, anything requiring information from
# a file header - e.g. SFF files where we would need to know the
# number of flows.

class SffDict(_IndexedSeqFileDict) :
    """Indexed dictionary like access to a Standard Flowgram Format (SFF) file."""
    def _setup(self):
        """Load the header information."""
        if self._alphabet is None:
            self._alphabet = Alphabet.generic_dna
        handle = self._handle
        #Record the what we'll need for parsing a record given its offset
        header_length, index_offset, index_length, number_of_reads, \
        self._flows_per_read, self._flow_chars, self._key_sequence \
            = SeqIO.SffIO._sff_file_header(handle)
    
    def _build(self):
        """Load any index block in the file, or build it the slow way (PRIVATE)."""
        handle = self._handle
        handle.seek(0)
        header_length, index_offset, index_length, number_of_reads, \
        self._flows_per_read, self._flow_chars, self._key_sequence \
            = SeqIO.SffIO._sff_file_header(handle)
        if index_offset and index_length:
            #There is an index provided, try this the fast way:
            try :
                for name, offset in SeqIO.SffIO._sff_read_roche_index(handle) :
                    self._record_key(name, offset)
                self._flush()
                assert len(self) == number_of_reads, \
                       "Indexed %i records, expected %i" \
                       % (len(self), number_of_reads)
                return
            except ValueError, err :
                import warnings
                warnings.warn("Could not parse the SFF index: %s" % err)
                assert len(self)==0
                handle.seek(0)
        else :
            #TODO - Remove this debug warning?
            import warnings
            warnings.warn("No SFF index, doing it the slow way")
        #Fall back on the slow way!
        for name, offset in SeqIO.SffIO._sff_do_slow_index(handle) :
            #print "%s -> %i" % (name, offset)
            self._record_key(name, offset)
        self._flush()
        assert len(self) == number_of_reads, \
               "Indexed %i records, expected %i" % (len(self), number_of_reads)
        
    def __getitem__(self, key) :
        handle = self._handle
        handle.seek(self._get_offset(key))
        record = SeqIO.SffIO._sff_read_seq_record(handle,
                                                  self._flows_per_read,
                                                  self._flow_chars,
                                                  self._key_sequence,
                                                  self._alphabet)
        assert record.id == key
        return record

class SffTrimmedDict(SffDict) :
    def __getitem__(self, key) :
        handle = self._handle
        handle.seek(self._get_offset(key))
        record = SeqIO.SffIO._sff_read_seq_record(handle,
                                                  self._flows_per_read,
                                                  self._flow_chars,
                                                  self._key_sequence,
                                                  self._alphabet,
                                                  trim=True)
        assert record.id == key
        return record

###################
# Simple indexers #
###################

class SequentialSeqFileDict(_IndexedSeqFileDict):
    """Indexed dictionary like access to most sequential sequence files."""
    def _setup(self):
        marker = {"ace" : "CO ",
                  "fasta": ">",
                  "phd" : "BEGIN_SEQUENCE",
                  "pir" : ">..;",
                  "qual": ">",
                   }[self._format]
        self._marker = marker
        self._marker_re = re.compile("^%s" % marker)

    def _build(self):
        handle = self._handle
        marker_re = self._marker_re
        marker_offset = len(self._marker)
        while True:
            offset = handle.tell()
            line = handle.readline()
            if not line : break #End of file
            if marker_re.match(line):
                #Here we can assume the record.id is the first word after the
                #marker. This is generally fine... but not for GenBank, EMBL, Swiss
                self._record_key(line[marker_offset:].strip().split(None, 1)[0], \
                                 offset)

    def get_raw(self, key):
        """Similar to the get method, but returns the record as a raw string."""
        #For non-trivial file formats this must be over-ridden in the subclass
        handle = self._handle
        marker_re = self._marker_re
        handle.seek(self._get_offset(key))
        data = handle.readline()
        while True:
            line = handle.readline()
            if not line or marker_re.match(line):
                #End of file, or start of next record => end of this record
                break
            data += line
        return data


#######################################
# Fiddly indexers: GenBank, EMBL, ... #
#######################################

class GenBankDict(SequentialSeqFileDict):
    """Indexed dictionary like access to a GenBank file."""
    def _setup(self):
        marker = "LOCUS "
        self._marker = marker
        self._marker_re = re.compile("^%s" % marker)
    
    def _build(self):
        handle = self._handle
        marker_re = self._marker_re
        while True:
            offset = handle.tell()
            line = handle.readline()
            if not line : break #End of file
            if marker_re.match(line):
                #We cannot assume the record.id is the first word after LOCUS,
                #normally the first entry on the VERSION or ACCESSION line is used.
                key = None
                done = False
                while not done:
                    line = handle.readline()
                    if line.startswith("ACCESSION "):
                        key = line.rstrip().split()[1]
                    elif line.startswith("VERSION "):
                        version_id = line.rstrip().split()[1]
                        if version_id.count(".")==1 and version_id.split(".")[1].isdigit():
                            #This should mimic the GenBank parser...
                            key = version_id
                            done = True
                            break
                    elif line.startswith("FEATURES ") \
                    or line.startswith("ORIGIN ") \
                    or line.startswith("//") \
                    or marker_re.match(line) \
                    or not line:
                        done = True
                        break
                if not key:
                    raise ValueError("Did not find ACCESSION/VERSION lines")
                self._record_key(key, offset)

class EmblDict(SequentialSeqFileDict):
    """Indexed dictionary like access to an EMBL file."""
    def _setup(self):
        marker = "ID "
        self._marker = marker
        self._marker_re = re.compile("^%s" % marker)
    
    def _build(self):
        handle = self._handle
        marker_re = self._marker_re
        while True:
            offset = handle.tell()
            line = handle.readline()
            if not line : break #End of file
            if marker_re.match(line):
                #We cannot assume the record.id is the first word after ID,
                #normally the SV line is used.
                if line[2:].count(";") == 6:
                    #Looks like the semi colon separated style introduced in 2006
                    parts = line[3:].rstrip().split(";")
                    if parts[1].strip().startswith("SV "):
                        #The SV bit gives the version
                        key = "%s.%s" \
                              % (parts[0].strip(), parts[1].strip().split()[1])
                    else:
                        key = parts[0].strip()
                elif line[2:].count(";") == 3:
                    #Looks like the pre 2006 style, take first word only
                    key = line[3:].strip().split(None,1)[0]
                else:
                    raise ValueError('Did not recognise the ID line layout:\n' + line)
                while True:
                    line = handle.readline()
                    if line.startswith("SV "):
                        key = line.rstrip().split()[1]
                        break
                    elif line.startswith("FH ") \
                    or line.startswith("FT ") \
                    or line.startswith("SQ ") \
                    or line.startswith("//") \
                    or marker_re.match(line) \
                    or not line:
                        break
                self._record_key(key, offset)

class SwissDict(SequentialSeqFileDict):
    """Indexed dictionary like access to a SwissProt file."""
    def _setup(self):
        marker = "ID "
        self._marker = marker
        self._marker_re = re.compile("^%s" % marker)
    
    def _build(self):
        handle = self._handle
        marker_re = self._marker_re
        while True:
            offset = handle.tell()
            line = handle.readline()
            if not line : break #End of file
            if marker_re.match(line):
                #We cannot assume the record.id is the first word after ID,
                #normally the following AC line is used.
                line = handle.readline()
                assert line.startswith("AC ")
                key = line[3:].strip().split(";")[0].strip()
                self._record_key(key, offset)

class IntelliGeneticsDict(SequentialSeqFileDict):
    """Indexed dictionary like access to a IntelliGenetics file."""
    def _setup(self):
        marker = ";"
        self._marker = marker
        self._marker_re = re.compile("^%s" % marker)
    
    def _build(self):
        handle = self._handle
        marker_re = self._marker_re
        while True:
            offset = handle.tell()
            line = handle.readline()
            if not line : break #End of file
            if marker_re.match(line):
                #Now look for the first line which doesn't start ";"
                while True:
                    line = handle.readline()
                    if not line:
                        raise ValueError("Premature end of file?")
                    if line[0] != ";" and line.strip():
                        key = line.split()[0]
                        self._record_key(key, offset)
                        break

class TabDict(_IndexedSeqFileDict):
    """Indexed dictionary like access to a simple tabbed file."""
    def _build(self):
        handle = self._handle
        while True:
            offset = handle.tell()
            line = handle.readline()
            if not line : break #End of file
            try:
                key = line.split("\t")[0]
            except ValueError, err:
                if not line.strip():
                    #Ignore blank lines
                    continue
                else:
                    raise err
            else:
                self._record_key(key, offset)

    def get_raw(self, key):
        """Like the get method, but returns the record as a raw string."""
        handle = self._handle
        handle.seek(self._get_offset(key))
        return handle.readline()

class FastqDict(_IndexedSeqFileDict):
    """Indexed dictionary like access to a FASTQ file (any supported variant).

    With FASTQ the records all start with a "@" line, but so can quality lines.
    Note this will cope with line-wrapped FASTQ files.
    """
    def _build(self):
        handle = self._handle
        pos = handle.tell()
        line = handle.readline()
        if not line:
            #Empty file!
            return
        if line[0] != "@":
            raise ValueError("Problem with FASTQ @ line:\n%s" % repr(line))
        while line:
            #assert line[0]=="@"
            #This record seems OK (so far)
            self._record_key(line[1:].rstrip().split(None, 1)[0], pos)
            #Find the seq line(s)
            seq_len = 0
            while line:
                line = handle.readline()
                if line.startswith("+") : break
                seq_len += len(line.strip())
            if not line:
                raise ValueError("Premature end of file in seq section")
            #assert line[0]=="+"
            #Find the qual line(s)
            qual_len = 0
            while line:
                if seq_len == qual_len:
                    #Should be end of record...
                    pos = handle.tell()
                    line = handle.readline()
                    if line and line[0] != "@":
                        ValueError("Problem with line %s" % repr(line))
                    break
                else:
                    line = handle.readline()
                    qual_len += len(line.strip())
            if seq_len != qual_len:
                raise ValueError("Problem with quality section")
        #print "EOF"

    def get_raw(self, key):
        """Similar to the get method, but returns the record as a raw string."""
        #TODO - Refactor this and the __init__ method to reduce code duplication?
        handle = self._handle
        handle.seek(self._get_offset(key))
        line = handle.readline()
        data = line
        if line[0] != "@":
            raise ValueError("Problem with FASTQ @ line:\n%s" % repr(line))
        identifier = line[1:].rstrip().split(None, 1)[0]
        if self._key_function:
            identifier = self._key_function(identifier)
        if key != identifier:
            raise ValueError("Key did not match")
        #Find the seq line(s)
        seq_len = 0
        while line:
            line = handle.readline()
            data += line
            if line.startswith("+") : break
            seq_len += len(line.strip())
        if not line:
            raise ValueError("Premature end of file in seq section")
        assert line[0]=="+"
        #Find the qual line(s)
        qual_len = 0
        while line:
            if seq_len == qual_len:
                #Should be end of record...
                pos = handle.tell()
                line = handle.readline()
                if line and line[0] != "@":
                    ValueError("Problem with line %s" % repr(line))
                break
            else:
                line = handle.readline()
                data += line
                qual_len += len(line.strip())
        if seq_len != qual_len:
            raise ValueError("Problem with quality section")
        return data


###############################################################################

_FormatToIndexedDict = {"ace" : SequentialSeqFileDict,
                        "embl" : EmblDict,
                        "fasta" : SequentialSeqFileDict,
                        "fastq" : FastqDict, #Class handles all three variants
                        "fastq-sanger" : FastqDict, #alias of the above
                        "fastq-solexa" : FastqDict,
                        "fastq-illumina" : FastqDict,
                        "genbank" : GenBankDict,
                        "gb" : GenBankDict, #alias of the above
                        "ig" : IntelliGeneticsDict,
                        "phd" : SequentialSeqFileDict,
                        "pir" : SequentialSeqFileDict,
                        "sff" : SffDict,
                        "sff-trim" : SffTrimmedDict,
                        "swiss" : SwissDict,
                        "tab" : TabDict,
                        "qual" : SequentialSeqFileDict,
                        }

