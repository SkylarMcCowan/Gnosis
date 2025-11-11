#!/usr/bin/env python3
"""
DuckDuckGo Search Debugging Script
Comprehensive testing of DuckDuckGo search functionality
"""

import time
import requests
from duckduckgo_search import DDGS
import signal
import sys
from colorama import Fore, Style, init

init(autoreset=True)

def test_basic_connectivity():
    """Test basic internet connectivity"""
    print(f"{Fore.CYAN}=== Testing Basic Connectivity ==={Style.RESET_ALL}")
    
    test_urls = [
        "https://www.google.com",
        "https://duckduckgo.com",
        "https://httpbin.org/get"
    ]
    
    for url in test_urls:
        try:
            start_time = time.time()
            response = requests.get(url, timeout=5)
            end_time = time.time()
            print(f"✓ {url}: {response.status_code} ({end_time - start_time:.2f}s)")
        except Exception as e:
            print(f"✗ {url}: {str(e)}")
    print()

def test_duckduckgo_versions():
    """Test different DuckDuckGo search approaches"""
    print(f"{Fore.CYAN}=== Testing DuckDuckGo Versions ==={Style.RESET_ALL}")
    
    # Test 1: Basic DDGS search
    print("1. Testing basic DDGS search...")
    try:
        start_time = time.time()
        with DDGS() as ddgs:
            results = list(ddgs.text("python programming", max_results=1))
        end_time = time.time()
        
        if results:
            print(f"✓ Basic search: Found {len(results)} results ({end_time - start_time:.2f}s)")
            print(f"   Sample: {results[0]['title'][:50]}...")
        else:
            print(f"✗ Basic search: No results ({end_time - start_time:.2f}s)")
    except Exception as e:
        print(f"✗ Basic search failed: {str(e)}")
    
    # Test 2: DDGS with different parameters
    print("\n2. Testing DDGS with different parameters...")
    test_configs = [
        {},  # Default config
        {"timeout": 15},  # Longer timeout
        {"timeout": 5},   # Shorter timeout
    ]
    
    for i, config in enumerate(test_configs):
        try:
            start_time = time.time()
            with DDGS(**config) as ddgs:
                results = list(ddgs.text("test query", max_results=1))
            end_time = time.time()
            
            if results:
                print(f"✓ Config {i+1} {config}: Success ({end_time - start_time:.2f}s)")
            else:
                print(f"⚠ Config {i+1} {config}: No results ({end_time - start_time:.2f}s)")
        except Exception as e:
            print(f"✗ Config {i+1} {config}: {str(e)[:100]}...")
    print()

def test_with_timeout_protection():
    """Test DuckDuckGo with various timeout protections"""
    print(f"{Fore.CYAN}=== Testing Timeout Protection Methods ==={Style.RESET_ALL}")
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Search timed out")
    
    # Test with signal-based timeout
    print("1. Testing with signal-based timeout (10s)...")
    try:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(10)
        
        start_time = time.time()
        with DDGS() as ddgs:
            results = list(ddgs.text("current news", max_results=2))
        
        signal.alarm(0)
        end_time = time.time()
        
        print(f"✓ Signal timeout: Found {len(results)} results ({end_time - start_time:.2f}s)")
        
    except TimeoutError:
        signal.alarm(0)
        print(f"✗ Signal timeout: Search exceeded 10 seconds")
    except Exception as e:
        signal.alarm(0)
        print(f"✗ Signal timeout: {str(e)[:100]}...")
    
    # Test with shorter max_results
    print("\n2. Testing with minimal results (max_results=1)...")
    try:
        start_time = time.time()
        with DDGS() as ddgs:
            results = list(ddgs.text("simple test", max_results=1))
        end_time = time.time()
        
        print(f"✓ Minimal results: Found {len(results)} results ({end_time - start_time:.2f}s)")
        
    except Exception as e:
        print(f"✗ Minimal results: {str(e)[:100]}...")
    print()

def test_different_queries():
    """Test with different types of queries"""
    print(f"{Fore.CYAN}=== Testing Different Query Types ==={Style.RESET_ALL}")
    
    test_queries = [
        "hello world",           # Simple query
        "python programming",    # Common topic
        "current news today",    # Current events (often problematic)
        "weather forecast",      # Location-based
        "2+2",                  # Math query
        "define artificial intelligence"  # Definition query
    ]
    
    for query in test_queries:
        try:
            start_time = time.time()
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=1))
            end_time = time.time()
            
            if results:
                print(f"✓ '{query}': Success ({end_time - start_time:.2f}s)")
            else:
                print(f"⚠ '{query}': No results ({end_time - start_time:.2f}s)")
                
        except Exception as e:
            print(f"✗ '{query}': {str(e)[:80]}...")
    print()

def test_duckduckgo_alternatives():
    """Test alternative DuckDuckGo approaches"""
    print(f"{Fore.CYAN}=== Testing Alternative Approaches ==={Style.RESET_ALL}")
    
    # Test 1: Direct HTTP request to DuckDuckGo
    print("1. Testing direct HTTP request to DuckDuckGo...")
    try:
        start_time = time.time()
        url = "https://duckduckgo.com/html/?q=test+query"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        end_time = time.time()
        
        if response.status_code == 200:
            print(f"✓ Direct HTTP: Status {response.status_code} ({end_time - start_time:.2f}s)")
            print(f"   Content length: {len(response.text)} chars")
        else:
            print(f"✗ Direct HTTP: Status {response.status_code}")
            
    except Exception as e:
        print(f"✗ Direct HTTP: {str(e)}")
    
    # Test 2: Check if it's a rate limiting issue
    print("\n2. Testing rate limiting (multiple quick searches)...")
    try:
        for i in range(3):
            start_time = time.time()
            with DDGS() as ddgs:
                results = list(ddgs.text(f"test query {i}", max_results=1))
            end_time = time.time()
            
            print(f"   Search {i+1}: {len(results)} results ({end_time - start_time:.2f}s)")
            time.sleep(1)  # Small delay between searches
            
    except Exception as e:
        print(f"✗ Rate limiting test: {str(e)}")
    print()

def main():
    """Run all DuckDuckGo debugging tests"""
    print(f"{Fore.GREEN}🔍 DuckDuckGo Search Debugging Tool{Style.RESET_ALL}")
    print(f"{Fore.GREEN}===================================={Style.RESET_ALL}\n")
    
    try:
        test_basic_connectivity()
        test_duckduckgo_versions()
        test_with_timeout_protection()
        test_different_queries()
        test_duckduckgo_alternatives()
        
    except KeyboardInterrupt:
        print(f"\n{Fore.YELLOW}Debugging interrupted by user{Style.RESET_ALL}")
    except Exception as e:
        print(f"\n{Fore.RED}Unexpected error: {str(e)}{Style.RESET_ALL}")
    
    print(f"\n{Fore.GREEN}Debugging complete!{Style.RESET_ALL}")

if __name__ == "__main__":
    main()