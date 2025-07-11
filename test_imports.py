#!/usr/bin/env python3
"""
Test script to verify all imports from run_agent.py are available in the virtual environment.
"""

import sys
import importlib
from typing import List, Tuple

def test_import(module_name: str, from_module: str = None, import_name: str = None) -> Tuple[bool, str]:
    """Test if a module or specific import can be imported."""
    try:
        if from_module:
            # Handle "from X import Y" style imports
            module = importlib.import_module(from_module)
            if import_name and import_name != "*":
                if hasattr(module, import_name):
                    return True, f"✅ from {from_module} import {import_name}"
                else:
                    return False, f"❌ from {from_module} import {import_name} - {import_name} not found in module"
            return True, f"✅ from {from_module} import *"
        else:
            # Handle "import X" style imports
            importlib.import_module(module_name)
            return True, f"✅ import {module_name}"
    except ImportError as e:
        if from_module:
            return False, f"❌ from {from_module} import {import_name or '*'} - {str(e)}"
        return False, f"❌ import {module_name} - {str(e)}"
    except Exception as e:
        if from_module:
            return False, f"❌ from {from_module} import {import_name or '*'} - Unexpected error: {str(e)}"
        return False, f"❌ import {module_name} - Unexpected error: {str(e)}"

def main():
    print("Testing imports from run_agent.py...\n")
    
    # List of imports to test based on run_agent.py
    imports_to_test = [
        # Standard library imports
        ("json", None, None),
        ("dataclasses", None, "asdict"),
        ("typing", None, "Optional"),
        ("textwrap", None, "dedent"),
        
        # Third-party imports
        ("art", None, None),
        ("litellm", None, None),
        ("litellm", None, "acompletion"),
        ("litellm.caching.caching", "litellm.caching.caching", "LiteLLMCacheType"),
        ("litellm.caching.caching", "litellm.caching.caching", "Cache"),
        ("rich", None, None),
        ("rich", "rich", "print"),
        ("dotenv", None, "load_dotenv"),
        ("langchain_core.utils.function_calling", "langchain_core.utils.function_calling", "convert_to_openai_tool"),
        ("pydantic", None, None),
        ("pydantic", "pydantic", "BaseModel"),
        ("pydantic", "pydantic", "Field"),
        ("tenacity", None, None),
        ("tenacity", "tenacity", "retry"),
        ("tenacity", "tenacity", "stop_after_attempt"),
        ("weave", None, None),
        ("art.utils.litellm", "art.utils.litellm", "convert_litellm_choice_to_openai"),
        
        # Local imports (these might fail if not in PYTHONPATH)
        ("lecture_search_tools", None, None),
        ("project_types", None, None),
    ]
    
    failed_imports = []
    successful_imports = []
    
    for import_info in imports_to_test:
        if len(import_info) == 3:
            module, from_module, import_name = import_info
            if from_module:
                success, message = test_import(module, from_module, import_name)
            else:
                success, message = test_import(module)
        else:
            module = import_info[0]
            success, message = test_import(module)
        
        print(message)
        if success:
            successful_imports.append(message)
        else:
            failed_imports.append(message)
    
    print(f"\n{'='*60}")
    print(f"Summary: {len(successful_imports)} successful, {len(failed_imports)} failed")
    print(f"{'='*60}")
    
    if failed_imports:
        print("\nFailed imports:")
        for fail in failed_imports:
            print(f"  {fail}")
        print("\nTo fix these issues, you may need to:")
        print("1. Install missing packages with: uv add <package_name>")
        print("2. Ensure local modules are in the PYTHONPATH")
        print("3. Check if the import paths are correct")
        sys.exit(1)
    else:
        print("\n✅ All imports are working correctly!")
        
    # Additional info
    print(f"\nPython version: {sys.version}")
    print(f"Python executable: {sys.executable}")

if __name__ == "__main__":
    main()