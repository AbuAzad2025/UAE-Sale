"""
Asset Compression and Minification Utilities
"""
import os
import gzip
import hashlib
from pathlib import Path
from flask import current_app


class AssetCompressor:
    """Compress and minify CSS/JS assets for production"""
    
    STATIC_DIR = 'static'
    CSS_DIR = 'css'
    JS_DIR = 'js'
    
    @staticmethod
    def minify_css(content):
        """Minify CSS content"""
        import re
        
        # Remove comments
        content = re.sub(r'/\*[^*]*\*+(?:[^/*][^*]*\*+)*/', '', content)
        
        # Remove whitespace
        content = re.sub(r'\s+', ' ', content)
        content = re.sub(r'\s*([{}:;,>+~])\s*', r'\1', content)
        
        # Remove last semicolon in blocks
        content = re.sub(r';}', '}', content)
        
        return content.strip()
    
    @staticmethod
    def minify_js(content):
        """Minify JavaScript content (basic)"""
        import re
        
        # Remove single-line comments
        content = re.sub(r'//.*?\n', '\n', content)
        
        # Remove multi-line comments
        content = re.sub(r'/\*.*?\*/', '', content, flags=re.DOTALL)
        
        # Remove extra whitespace
        content = re.sub(r'\s+', ' ', content)
        content = re.sub(r'\s*([{}();,:])\s*', r'\1', content)
        
        return content.strip()
    
    @staticmethod
    def gzip_file(file_path):
        """Create gzipped version of file"""
        gz_path = f"{file_path}.gz"
        
        with open(file_path, 'rb') as f_in:
            with gzip.open(gz_path, 'wb', compresslevel=9) as f_out:
                f_out.writelines(f_in)
        
        return gz_path
    
    @staticmethod
    def get_file_hash(content):
        """Get MD5 hash of content"""
        return hashlib.md5(content.encode()).hexdigest()[:8]
    
    @classmethod
    def process_css_files(cls, base_dir='static/css'):
        """Process all CSS files"""
        results = []
        css_dir = Path(base_dir)
        
        if not css_dir.exists():
            return results
        
        for css_file in css_dir.glob('**/*.css'):
            if css_file.name.endswith('.min.css'):
                continue
            
            try:
                # Read original
                with open(css_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Minify
                minified = cls.minify_css(content)
                
                # Save minified version
                min_path = css_file.parent / f"{css_file.stem}.min.css"
                with open(min_path, 'w', encoding='utf-8') as f:
                    f.write(minified)
                
                # Gzip
                gz_path = cls.gzip_file(str(min_path))
                
                original_size = len(content)
                minified_size = len(minified)
                gz_size = os.path.getsize(gz_path)
                
                results.append({
                    'file': str(css_file.name),
                    'original': original_size,
                    'minified': minified_size,
                    'gzipped': gz_size,
                    'savings': round((1 - gz_size/original_size) * 100, 2)
                })
                
                print(f"✅ {css_file.name}: {original_size} → {minified_size} → {gz_size} bytes ({results[-1]['savings']}% saved)")
                
            except Exception as e:
                print(f"❌ Error processing {css_file}: {e}")
        
        return results
    
    @classmethod
    def process_js_files(cls, base_dir='static/js'):
        """Process all JS files"""
        results = []
        js_dir = Path(base_dir)
        
        if not js_dir.exists():
            return results
        
        for js_file in js_dir.glob('**/*.js'):
            if js_file.name.endswith('.min.js'):
                continue
            
            try:
                # Read original
                with open(js_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                # Minify (basic)
                minified = cls.minify_js(content)
                
                # Save minified version
                min_path = js_file.parent / f"{js_file.stem}.min.js"
                with open(min_path, 'w', encoding='utf-8') as f:
                    f.write(minified)
                
                # Gzip
                gz_path = cls.gzip_file(str(min_path))
                
                original_size = len(content)
                minified_size = len(minified)
                gz_size = os.path.getsize(gz_path)
                
                results.append({
                    'file': str(js_file.name),
                    'original': original_size,
                    'minified': minified_size,
                    'gzipped': gz_size,
                    'savings': round((1 - gz_size/original_size) * 100, 2)
                })
                
                print(f"✅ {js_file.name}: {original_size} → {minified_size} → {gz_size} bytes ({results[-1]['savings']}% saved)")
                
            except Exception as e:
                print(f"❌ Error processing {js_file}: {e}")
        
        return results
    
    @classmethod
    def compress_all(cls):
        """Compress all assets"""
        print("🔧 Starting asset compression...")
        
        css_results = cls.process_css_files()
        js_results = cls.process_js_files()
        
        total_original = sum(r['original'] for r in css_results + js_results)
        total_compressed = sum(r['gzipped'] for r in css_results + js_results)
        
        print("\n" + "="*60)
        print("📊 Compression Summary")
        print("="*60)
        print(f"CSS Files: {len(css_results)}")
        print(f"JS Files: {len(js_results)}")
        print(f"Total Original: {total_original:,} bytes")
        print(f"Total Compressed: {total_compressed:,} bytes")
        print(f"Total Savings: {round((1 - total_compressed/total_original) * 100, 2)}%")
        print("="*60)
        
        return {
            'css': css_results,
            'js': js_results,
            'total_savings': round((1 - total_compressed/total_original) * 100, 2)
        }


def register_compression_cli(app):
    """Register CLI commands for asset compression"""
    
    @app.cli.command('compress-assets')
    def compress_assets():
        """Compress CSS and JS assets"""
        results = AssetCompressor.compress_all()
        print(f"\n✅ Asset compression completed!")
        print(f"📦 Total savings: {results['total_savings']}%")

