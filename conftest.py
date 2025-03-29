"""
Global conftest.py to help with imports and test setup
"""
import os
import sys

# Add the src directory to Python's module search path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "src"))) 