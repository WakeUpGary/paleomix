from nose.tools import assert_equal
import nose.tools

from pypeline.common.formats.phylip import *
from pypeline.common.formats.msa import MSAError


################################################################################
################################################################################
## Tests of 'sequential_phy'

def test_sequential_phy__short_sequences():
    msa = { "seq1" : "ACGTTGATAACCAGGAGGGATTCGCGATTGGTGGTAACGTAGCC", 
            "seq2" : "TGCAGAGTACGACGTCTCCTAGATCCTGGACAATTTAAACCGAA" }
    expected = \
"""2 44

seq1
ACGTTGATAA  CCAGGAGGGA  TTCGCGATTG  GTGGTAACGT  AGCC
seq2
TGCAGAGTAC  GACGTCTCCT  AGATCCTGGA  CAATTTAAAC  CGAA"""
    assert_equal(sequential_phy(msa), expected)  


def test_sequential_phy__multi_line_sequences():
    msa = { "seq1" : "CGGATCTGCTCCTCCACTGGCCACGTTTACTGTCCCCCAACCGTTCGTCCCGACCTAGTTATACTTCTTAGCAAGGTGTAAAACCAGAGATTGAGGTTATAACGTTCCTAATCAGTTATTAAATTACCGCGCCCCGACAG", 
            "seq2" : "AGTTGAAGAGGCGGAACGTTTGTAAACCGCGCTAACGTAGTTCTACAACCAGCCACCCGGTTCGAAGGAACAACTGGTCGCCATAATTAGGCGAAACGATAGTGCACTAAGGTCAGGTGCGCCCCTGTAAATAATTAGAT" }
    expected = \
"""2 140

seq1
CGGATCTGCT  CCTCCACTGG  CCACGTTTAC  TGTCCCCCAA  CCGTTCGTCC  CGACCTAGTT
ATACTTCTTA  GCAAGGTGTA  AAACCAGAGA  TTGAGGTTAT  AACGTTCCTA  ATCAGTTATT
AAATTACCGC  GCCCCGACAG
seq2
AGTTGAAGAG  GCGGAACGTT  TGTAAACCGC  GCTAACGTAG  TTCTACAACC  AGCCACCCGG
TTCGAAGGAA  CAACTGGTCG  CCATAATTAG  GCGAAACGAT  AGTGCACTAA  GGTCAGGTGC
GCCCCTGTAA  ATAATTAGAT"""
    assert_equal(sequential_phy(msa), expected)  


def test_sequential_phy__with_flag():
    msa = { "seq1" : "ACGTTGATAACCAGG", 
            "seq2" : "TGCAGAGTACGACGT" }
    expected = \
"""2 15 S

seq1
ACGTTGATAA  CCAGG
seq2
TGCAGAGTAC  GACGT"""
    assert_equal(sequential_phy(msa, add_flag = True), expected)  


def test_sequentual_phy__long_names():
    msa = { "A_really_long_sequence_name_that_is_in_fact_too_long" : "ACGTTGATAACCAGG", 
            "Another_really_long_sequence_name_that_is_too_long" : "TGCAGAGTACGACGT" }
    expected = \
"""2 15

A_really_long_sequence_name_th
ACGTTGATAA  CCAGG
Another_really_long_sequence_n
TGCAGAGTAC  GACGT"""
    assert_equal(sequential_phy(msa), expected)  


@nose.tools.raises(MSAError)
def test_sequential_phy__empty_msa():
    sequential_phy({})

@nose.tools.raises(MSAError)
def test_sequential_phy__different_lengths():
    sequential_phy({"seq1" : "A", "seq2" : "TC"})



################################################################################
################################################################################
## Tests of 'interleaved_phy'

def test_interleaved_phy__short_sequences():
    msa = { "seq1" : "ACGTTGATAACCAGGAGGGATTCGCGATTGGTGGTAACGTAGCC", 
            "seq2" : "TGCAGAGTACGACGTCTCCTAGATCCTGGACAATTTAAACCGAA" }
    expected = \
"""2 44

seq1        ACGTTGATAA  CCAGGAGGGA  TTCGCGATTG  GTGGTAACGT  AGCC
seq2        TGCAGAGTAC  GACGTCTCCT  AGATCCTGGA  CAATTTAAAC  CGAA"""
    assert_equal(interleaved_phy(msa), expected)  


def test_interleaved_phy__multi_line_sequences():
    msa = { "seq1" : "CGGATCTGCTCCTCCACTGGCCACGTTTACTGTCCCCCAACCGTTCGTCCCGACCTAGTTATACTTCTTAGCAAGGTGTAAAACCAGAGATTGAGGTTATAACGTTCCTAATCAGTTATTAAATTACCGCGCCCCGACAG", 
            "seq2" : "AGTTGAAGAGGCGGAACGTTTGTAAACCGCGCTAACGTAGTTCTACAACCAGCCACCCGGTTCGAAGGAACAACTGGTCGCCATAATTAGGCGAAACGATAGTGCACTAAGGTCAGGTGCGCCCCTGTAAATAATTAGAT" }
    expected = \
"""2 140

seq1        CGGATCTGCT  CCTCCACTGG  CCACGTTTAC  TGTCCCCCAA  CCGTTCGTCC
seq2        AGTTGAAGAG  GCGGAACGTT  TGTAAACCGC  GCTAACGTAG  TTCTACAACC

CGACCTAGTT  ATACTTCTTA  GCAAGGTGTA  AAACCAGAGA  TTGAGGTTAT  AACGTTCCTA
AGCCACCCGG  TTCGAAGGAA  CAACTGGTCG  CCATAATTAG  GCGAAACGAT  AGTGCACTAA

ATCAGTTATT  AAATTACCGC  GCCCCGACAG
GGTCAGGTGC  GCCCCTGTAA  ATAATTAGAT"""
    assert_equal(interleaved_phy(msa), expected)  


def test_interleaved_phy__with_flag():
    msa = { "seq1" : "ACGTTGATAACCAGG", 
            "seq2" : "TGCAGAGTACGACGT" }
    expected = \
"""2 15 I

seq1        ACGTTGATAA  CCAGG
seq2        TGCAGAGTAC  GACGT"""
    assert_equal(interleaved_phy(msa, add_flag = True), expected)  


def test_sequentual_phy__medium_names():
    msa = { "A_really_long_sequence" : "ACGTTGATAACCAGG", 
            "Another_real_long_one!" : "TGCAGAGTACGACGT" }
    expected = \
"""2 15

A_really_long_sequence  ACGTTGATAA  CCAGG
Another_real_long_one!  TGCAGAGTAC  GACGT"""
    assert_equal(interleaved_phy(msa), expected)  


def test_sequentual_phy__long_names():
    msa = { "A_really_long_sequence_name_that_is_in_fact_too_long" : "ACGTTGATAACCAGG", 
            "Another_really_long_sequence_name_that_is_too_long" : "TGCAGAGTACGACGT" }
    expected = \
"""2 15

A_really_long_sequence_name_th      ACGTTGATAA  CCAGG
Another_really_long_sequence_n      TGCAGAGTAC  GACGT"""
    assert_equal(interleaved_phy(msa), expected)  


def test_sequentual_phy__different_length_names_1():
    msa = { "A_short_name" : "ACGTTGATAACCAGG", 
            "Another_really_long_sequence_name_that_is_too_long" : "TGCAGAGTACGACGT" }
    expected = \
"""2 15

A_short_name                        ACGTTGATAA  CCAGG
Another_really_long_sequence_n      TGCAGAGTAC  GACGT"""
    print interleaved_phy(msa), expected
    assert_equal(interleaved_phy(msa), expected)  


def test_sequentual_phy__different_length_names_2():
    msa = { "Burchelli_4" : "ACGTTGATAACCAGG", 
            "Donkey" : "TGCAGAGTACGACGT" }
    expected = \
"""2 15

Burchelli_4             ACGTTGATAA  CCAGG
Donkey                  TGCAGAGTAC  GACGT"""
    print interleaved_phy(msa), expected
    assert_equal(interleaved_phy(msa), expected)  


@nose.tools.raises(MSAError)
def test_interleaved_phy__empty_msa():
    interleaved_phy({})

@nose.tools.raises(MSAError)
def test_interleaved_phy__different_lengths():
    interleaved_phy({"seq1" : "A", "seq2" : "TC"})