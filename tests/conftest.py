"""Tests run with the smallest draft tier whatever the machine has, so the
limits they check (3,000 characters, 80 units) are the same everywhere."""
import os

os.environ.setdefault('VOXSTAGE_DRAFT_CHARS', '3000')
