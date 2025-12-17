from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import yt_dlp
import os
import uuid
from typing import Optional, Dict, Any, List

app = FastAPI(title="Universal Video Downloader API v2.8")

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request models
class VideoURLRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    format_id: Optional[str] = None


# ============ HELPER FUNCTIONS ============

def safe_int(value, default=0):
    """Safely convert to int, handle None/null"""
    if value is None or value == '':
        return default
    try:
        return int(float(value))
    except:
        return default


def safe_float(value, default=0.0):
    """Safely convert to float"""
    if value is None or value == '':
        return default
    try:
        return float(value)
    except:
        return default


def safe_compare(value, default=0):
    """
    CRITICAL: Safe comparison helper - prevents NoneType comparison errors
    Returns an integer that can be safely compared
    """
    if value is None:
        return default
    try:
        return int(float(value))
    except:
        return default


def is_tiktok_url(url: str) -> bool:
    """Check if URL is from TikTok"""
    return 'tiktok.com' in url.lower()


def is_instagram_url(url: str) -> bool:
    """Check if URL is from Instagram"""
    return 'instagram.com' in url.lower()


def detect_format_type(fmt: Dict) -> str:
    """
    ROBUST format type detection - handles None values
    Returns: 'audio', 'video', or 'complete'
    """
    # CRITICAL: Handle None values before ANY comparisons
    vcodec_raw = fmt.get('vcodec')
    acodec_raw = fmt.get('acodec')
    
    # Convert None to 'none' string
    vcodec = str(vcodec_raw if vcodec_raw is not None else 'none').lower().strip()
    acodec = str(acodec_raw if acodec_raw is not None else 'none').lower().strip()
    
    format_id = str(fmt.get('format_id') or '').lower()
    format_note = str(fmt.get('format_note') or '').lower()
    ext = str(fmt.get('ext') or '').lower()
    
    # SAFE dimension extraction
    height = safe_int(fmt.get('height'))
    width = safe_int(fmt.get('width'))
    
    # ===== AUDIO DETECTION =====
    audio_keywords = ['audio', 'mp3', 'm4a', 'opus', 'aac']
    if any(keyword in format_id for keyword in audio_keywords):
        return 'audio'
    if any(keyword in format_note for keyword in audio_keywords):
        return 'audio'
    
    # ===== CODEC-BASED DETECTION =====
    if vcodec == 'none' and acodec != 'none':
        return 'audio'
    
    if vcodec != 'none' and acodec == 'none':
        return 'video'
    
    if vcodec not in ['none', 'unknown', ''] and acodec not in ['none', 'unknown', '']:
        return 'complete'
    
    # ===== DIMENSION CHECK =====
    if (height > 0 or width > 0) and acodec == 'none':
        return 'video'
    
    if (height > 0 or width > 0) and vcodec in ['unknown', ''] and acodec in ['unknown', '']:
        return 'complete'
    
    # ===== EXTENSION FALLBACK =====
    audio_exts = ['m4a', 'mp3', 'aac', 'opus', 'ogg', 'flac', 'wav']
    if ext in audio_exts:
        return 'audio'
    
    video_exts = ['mp4', 'webm', 'mkv', 'flv', 'avi']
    if ext in video_exts and (height > 0 or width > 0):
        protocol = str(fmt.get('protocol', '')).lower()
        
        if 'h264' in format_id or 'bytevc1' in format_id:
            filesize = fmt.get('filesize') or fmt.get('filesize_approx', 0)
            if filesize and filesize > 100000:
                return 'complete'
        
        if protocol in ['m3u8_native', 'm3u8', 'http_dash_segments']:
            return 'video'
        
        if protocol in ['https', 'http']:
            filesize = fmt.get('filesize') or fmt.get('filesize_approx', 0)
            if filesize and filesize > 500000:
                return 'complete'
            return 'video'
    
    return 'unknown'


def calculate_bitrate(fmt: Dict) -> int:
    """Calculate bitrate - SAFE against None"""
    bitrate = (
        safe_int(fmt.get('tbr')) or 
        safe_int(fmt.get('vbr')) or 
        safe_int(fmt.get('abr')) or
        safe_int(fmt.get('bitrate'))
    )
    
    if bitrate == 0:
        asr = safe_int(fmt.get('asr'))
        if asr > 0:
            bitrate = int(asr / 1000 * 0.128)
    
    if bitrate == 0:
        ext = str(fmt.get('ext', '')).lower()
        default_bitrates = {
            'm4a': 128, 'mp3': 192, 'aac': 128,
            'opus': 96, 'mp4': 500, 'webm': 400
        }
        bitrate = default_bitrates.get(ext, 128)
    
    return bitrate


def get_filesize_mb(fmt: Dict) -> float:
    """Get filesize in MB - SAFE against None"""
    filesize = fmt.get('filesize') or fmt.get('filesize_approx')
    if filesize and filesize > 0:
        return round(filesize / (1024 * 1024), 2)
    return 0.0


def format_resolution(height, width) -> str:
    """Format resolution label - SAFE against None"""
    h = safe_int(height)
    w = safe_int(width)
    
    if h > 0:
        return f"{h}p"
    elif w > 0:
        return f"{w}p"
    return "unknown"


# ============ INSTAGRAM-SPECIFIC PARSER ============

def parse_instagram_formats(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    INSTAGRAM parser - FULLY handles None values in ALL comparisons
    """
    formats = data.get('formats', [])
    
    result = {
        'video_info': {
            'id': data.get('id', ''),
            'title': data.get('title', 'Unknown'),
            'duration': safe_float(data.get('duration')),
            'thumbnail': data.get('thumbnail', ''),
            'uploader': data.get('uploader', 'Unknown'),
            'webpage_url': data.get('webpage_url', ''),
            'platform': 'Instagram'
        },
        'complete_videos': [],
        'video_only': [],
        'audio_only': []
    }
    
    seen_complete = set()
    seen_video = set()
    seen_audio = set()
    
    for fmt in formats:
        format_id = str(fmt.get('format_id', ''))
        ext = str(fmt.get('ext') or '').lower()
        
        # Skip bad formats
        if any(x in format_id.lower() for x in ['sb-', 'storyboard', '-drc']):
            continue
        if ext in ['mhtml', '3gp']:
            continue
        
        # SAFE codec handling
        vcodec_raw = fmt.get('vcodec')
        acodec_raw = fmt.get('acodec')
        
        vcodec = str(vcodec_raw if vcodec_raw is not None else 'none').lower().strip()
        acodec = str(acodec_raw if acodec_raw is not None else 'none').lower().strip()
        
        # SAFE numeric extraction - NO None values
        height = safe_int(fmt.get('height'))
        width = safe_int(fmt.get('width'))
        tbr = safe_int(fmt.get('tbr'))
        filesize_mb = get_filesize_mb(fmt)
        
        # Detect format type
        format_type = detect_format_type(fmt)
        
        if format_type == 'unknown':
            # Instagram: unknown codec but valid dimensions = complete
            if height > 0 and width > 0:
                format_type = 'complete'
            else:
                continue
        
        # === AUDIO ===
        if format_type == 'audio':
            bitrate = calculate_bitrate(fmt)
            acodec_clean = str(acodec_raw if acodec_raw is not None else 'unknown')
            if '.' in acodec_clean:
                acodec_clean = acodec_clean.split('.')[0]
            
            audio_key = f"{ext}_{bitrate}_{acodec_clean}"
            if audio_key in seen_audio:
                continue
            seen_audio.add(audio_key)
            
            result['audio_only'].append({
                'id': format_id,
                'ext': ext.upper(),
                'codec': acodec_clean,
                'bitrate': bitrate,
                'size_mb': filesize_mb,
                'protocol': fmt.get('protocol', 'https'),
                'label': f"Audio {ext.upper()} {bitrate}kbps"
            })
            continue
        
        # === VIDEO ONLY ===
        if format_type == 'video':
            vcodec_clean = str(vcodec_raw if vcodec_raw is not None else 'unknown')
            codec_short = vcodec_clean.split('.')[0] if '.' in vcodec_clean else vcodec_clean
            
            res_label = format_resolution(height, width)
            video_key = f"{res_label}_{ext}_{codec_short}_{tbr}"
            if video_key in seen_video:
                continue
            seen_video.add(video_key)
            
            result['video_only'].append({
                'id': format_id,
                'ext': ext.upper(),
                'resolution': res_label,
                'width': width,
                'height': height,
                'fps': safe_int(fmt.get('fps')) or None,
                'codec': codec_short,
                'tbr': tbr,
                'size_mb': filesize_mb,
                'protocol': fmt.get('protocol', 'https'),
                'label': f"{ext.upper()} {res_label}"
            })
            continue
        
        # === COMPLETE VIDEOS ===
        if format_type == 'complete':
            res_label = format_resolution(height, width)
            complete_key = f"{res_label}_{ext}_{tbr}"
            if complete_key in seen_complete:
                continue
            seen_complete.add(complete_key)
            
            result['complete_videos'].append({
                'id': format_id,
                'ext': ext.upper(),
                'resolution': res_label,
                'width': width,
                'height': height,
                'tbr': tbr,
                'size_mb': filesize_mb,
                'protocol': fmt.get('protocol', 'https'),
                'label': f"{ext.upper()} {res_label} (Complete)"
            })
    
    return organize_and_enhance(result, 'Instagram')


# ============ TIKTOK-SPECIFIC PARSER ============

def parse_tiktok_formats(data: Dict[str, Any]) -> Dict[str, Any]:
    """TIKTOK parser"""
    formats = data.get('formats', [])
    
    result = {
        'video_info': {
            'id': data.get('id', ''),
            'title': data.get('title', 'Unknown'),
            'duration': safe_float(data.get('duration')),
            'thumbnail': data.get('thumbnail', ''),
            'uploader': data.get('uploader', 'Unknown'),
            'webpage_url': data.get('webpage_url', ''),
            'platform': 'TikTok'
        },
        'complete_videos': [],
        'video_only': [],
        'audio_only': []
    }
    
    seen_formats = set()
    
    for fmt in formats:
        format_id = str(fmt.get('format_id', ''))
        vcodec_raw = fmt.get('vcodec')
        acodec_raw = fmt.get('acodec')
        
        vcodec = str(vcodec_raw if vcodec_raw is not None else 'none').lower().strip()
        acodec = str(acodec_raw if acodec_raw is not None else 'none').lower().strip()
        ext = str(fmt.get('ext') or '').lower()
        
        if format_id == 'download':
            continue
        
        height = safe_int(fmt.get('height'))
        width = safe_int(fmt.get('width'))
        tbr = safe_int(fmt.get('tbr'))
        filesize_mb = get_filesize_mb(fmt)
        
        if vcodec in ['h264', 'h265'] and acodec == 'aac':
            res_label = format_resolution(height, width)
            
            if format_id in seen_formats:
                continue
            seen_formats.add(format_id)
            
            result['complete_videos'].append({
                'id': format_id,
                'ext': ext.upper(),
                'resolution': res_label,
                'width': width,
                'height': height,
                'codec': vcodec,
                'tbr': tbr,
                'size_mb': filesize_mb,
                'protocol': fmt.get('protocol', 'https'),
                'label': f"{ext.upper()} {res_label} ({vcodec})"
            })
    
    # SAFE sorting - use safe_compare
    result['complete_videos'].sort(
        key=lambda x: safe_compare(x.get('height')), 
        reverse=True
    )
    
    if result['complete_videos']:
        best = result['complete_videos'][0]
        result['audio_only'].append({
            'id': 'mp3_320',
            'ext': 'MP3',
            'codec': 'mp3',
            'bitrate': 320,
            'size_mb': 0,
            'protocol': 'convert',
            'label': 'MP3 320kbps (converted)',
            'convert': True,
            'source': best['id']
        })
    
    return result


# ============ GENERIC PARSER ============

def parse_formats_intelligent(data: Dict[str, Any]) -> Dict[str, Any]:
    """GENERIC parser for all other platforms"""
    formats = data.get('formats', [])
    platform = data.get('extractor_key', 'Unknown')
    
    result = {
        'video_info': {
            'id': data.get('id', ''),
            'title': data.get('title', 'Unknown'),
            'duration': safe_float(data.get('duration')),
            'thumbnail': data.get('thumbnail', ''),
            'uploader': data.get('uploader', 'Unknown'),
            'webpage_url': data.get('webpage_url', ''),
            'platform': platform
        },
        'complete_videos': [],
        'video_only': [],
        'audio_only': []
    }
    
    seen_complete = set()
    seen_video = set()
    seen_audio = set()
    
    for fmt in formats:
        ext = str(fmt.get('ext') or '').lower()
        format_id = str(fmt.get('format_id') or '')
        
        if ext in ['mhtml', '3gp']:
            continue
        if any(x in format_id.lower() for x in ['-drc', 'storyboard', 'sb-']):
            continue
        
        height = safe_int(fmt.get('height'))
        width = safe_int(fmt.get('width'))
        
        if format_id in ['sd', 'hd'] and height == 0 and width == 0:
            continue
        
        fps = safe_int(fmt.get('fps'))
        filesize_mb = get_filesize_mb(fmt)
        
        format_type = detect_format_type(fmt)
        
        if format_type == 'unknown':
            continue
        
        if format_type == 'audio':
            bitrate = calculate_bitrate(fmt)
            acodec_raw = fmt.get('acodec')
            acodec = str(acodec_raw if acodec_raw is not None else 'unknown')
            
            if '.' in acodec:
                acodec = acodec.split('.')[0]
            
            audio_key = f"{ext}_{bitrate}_{acodec}"
            if audio_key in seen_audio:
                continue
            seen_audio.add(audio_key)
            
            result['audio_only'].append({
                'id': format_id,
                'ext': ext.upper(),
                'codec': acodec,
                'bitrate': bitrate,
                'size_mb': filesize_mb,
                'protocol': fmt.get('protocol', 'https'),
                'label': f"Audio {ext.upper()} {bitrate}kbps"
            })
            continue
        
        if format_type == 'video':
            vcodec_raw = fmt.get('vcodec')
            vcodec = str(vcodec_raw if vcodec_raw is not None else 'unknown')
            codec_short = vcodec.split('.')[0] if '.' in vcodec else vcodec
            
            tbr = calculate_bitrate(fmt)
            res_label = format_resolution(height, width)
            
            video_key = f"{res_label}_{ext}_{codec_short}_{tbr}"
            if video_key in seen_video:
                continue
            seen_video.add(video_key)
            
            result['video_only'].append({
                'id': format_id,
                'ext': ext.upper(),
                'resolution': res_label,
                'width': width,
                'height': height,
                'fps': fps if fps > 0 else None,
                'codec': codec_short,
                'tbr': tbr,
                'size_mb': filesize_mb,
                'protocol': fmt.get('protocol', 'https'),
                'label': f"{ext.upper()} {res_label}"
            })
            continue
        
        if format_type == 'complete':
            tbr = calculate_bitrate(fmt)
            res_label = format_resolution(height, width)
            
            complete_key = f"{res_label}_{ext}_{tbr}"
            if complete_key in seen_complete:
                continue
            seen_complete.add(complete_key)
            
            result['complete_videos'].append({
                'id': format_id,
                'ext': ext.upper(),
                'resolution': res_label,
                'width': width,
                'height': height,
                'tbr': tbr,
                'size_mb': filesize_mb,
                'protocol': fmt.get('protocol', 'https'),
                'label': f"{ext.upper()} {res_label} (Complete)"
            })
    
    return organize_and_enhance(result, platform)


def organize_and_enhance(categorized: Dict[str, Any], platform: str) -> Dict[str, Any]:
    """
    Organize and sort - CRITICAL: Use safe_compare for ALL comparisons
    """
    
    resolution_map = {
        '4320p': 13, '2160p': 12, '1920p': 11, '1440p': 10, '1280p': 9,
        '1080p': 8, '960p': 7, '852p': 6, '720p': 5, '640p': 4,
        '568p': 3, '480p': 2, '416p': 1.5, '360p': 1, '240p': 0.5
    }
    
    def quality_score(fmt):
        """SAFE scoring function - prevents None comparison errors"""
        res = resolution_map.get(fmt.get('resolution', 'unknown'), 0)
        tbr = safe_compare(fmt.get('tbr'), 0)
        return res * 1000 + tbr
    
    # SAFE sorting with error handling
    try:
        categorized['complete_videos'].sort(key=quality_score, reverse=True)
    except Exception:
        pass
    
    try:
        categorized['video_only'].sort(key=quality_score, reverse=True)
    except Exception:
        pass
    
    try:
        categorized['audio_only'].sort(
            key=lambda x: safe_compare(x.get('bitrate'), 0), 
            reverse=True
        )
    except Exception:
        pass
    
    # Add MP3 conversion
    audio = categorized['audio_only']
    if audio:
        has_mp3 = any(a.get('ext') == 'MP3' for a in audio)
        if not has_mp3:
            mp3_option = {
                'id': 'mp3_320',
                'ext': 'MP3',
                'codec': 'mp3',
                'bitrate': 320,
                'size_mb': 0,
                'protocol': 'convert',
                'label': 'MP3 320kbps (converted)',
                'convert': True,
                'source': audio[0]['id']
            }
            audio.insert(0, mp3_option)
    
    if not audio and categorized['complete_videos']:
        best_video = categorized['complete_videos'][0]
        audio.append({
            'id': 'mp3_320',
            'ext': 'MP3',
            'codec': 'mp3',
            'bitrate': 320,
            'size_mb': 0,
            'protocol': 'convert',
            'label': 'MP3 320kbps (converted)',
            'convert': True,
            'source': best_video['id']
        })
    
    return categorized


# ============ MAIN PARSER ROUTER ============

def get_video_formats(url: str) -> Dict[str, Any]:
    """Get all available formats - routes to correct parser"""
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
        'noplaylist': True,
        'extract_flat': False,
    }
    
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # ROUTE TO CORRECT PARSER
            if is_instagram_url(url):
                return parse_instagram_formats(info)
            elif is_tiktok_url(url):
                return parse_tiktok_formats(info)
            else:
                return parse_formats_intelligent(info)
                
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to extract formats: {str(e)}")


def download_video(url: str, format_id: Optional[str] = None, output_dir: str = "downloads") -> str:
    """Download video with smart format selection"""
    os.makedirs(output_dir, exist_ok=True)
    
    download_id = str(uuid.uuid4())[:8]
    
    ydl_opts = {
        'outtmpl': os.path.join(output_dir, f'{download_id}_%(title).80s.%(ext)s'),
        'quiet': False,
        'no_warnings': False,
        'noplaylist': True,
        'retries': 10,
        'fragment_retries': 10,
    }
    
    if format_id and format_id != 'auto':
        if format_id.startswith('m4a_extract_') or format_id == 'mp3_320':
            ydl_opts['format'] = 'bestaudio/best'
            ydl_opts['postprocessors'] = [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3' if 'mp3' in format_id else 'm4a',
                'preferredquality': '320' if 'mp3' in format_id else '256',
            }]
        else:
            ydl_opts['format'] = format_id
    else:
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
        ydl_opts['merge_output_format'] = 'mp4'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            filename = ydl.prepare_filename(info)
            
            if format_id and ('m4a_extract' in format_id or format_id == 'mp3_320'):
                base = os.path.splitext(filename)[0]
                for ext in ['.mp3', '.m4a', '.opus']:
                    if os.path.exists(base + ext):
                        return base + ext
            
            if not os.path.exists(filename):
                filename = os.path.splitext(filename)[0] + ".mp4"
            
            if os.path.exists(filename):
                return filename
            else:
                raise FileNotFoundError(f"File not found: {filename}")
            
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Download failed: {str(e)}")


# ============ API ENDPOINTS ============

@app.get("/")
def root():
    """API information"""
    return {
        "name": "Universal Video Downloader API",
        "version": "2.8.0",
        "status": "✅ Instagram FULLY Fixed - All None Comparisons Handled",
        "improvements": [
            "✅ CRITICAL: safe_compare() prevents ALL None comparison errors",
            "✅ FIXED: Sorting functions now handle None values",
            "✅ Instagram: Complete None-safe parsing",
            "✅ TikTok: None-safe sorting",
            "✅ All platforms: Robust error handling"
        ],
        "supported_platforms": "1000+ (Instagram, YouTube, TikTok, Twitter, Facebook, etc.)",
        "endpoints": {
            "/formats": "POST - Get formats",
            "/download": "POST - Download video/audio"
        }
    }


@app.post("/formats")
def get_formats(request: VideoURLRequest):
    """Get all available formats for a video URL"""
    try:
        formats = get_video_formats(request.url)
        return JSONResponse(content=formats)
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/download")
def download(request: DownloadRequest):
    """Download video with optional format selection"""
    try:
        filepath = download_video(request.url, request.format_id)
        filename = os.path.basename(filepath)
        
        ext = os.path.splitext(filename)[1].lower()
        media_type = 'audio/mpeg' if ext == '.mp3' else 'video/mp4'
        
        return FileResponse(
            path=filepath,
            filename=filename,
            media_type=media_type,
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    print("="*70)
    print("🚀 Universal Video Downloader API v2.8 - INSTAGRAM FULLY FIXED")
    print("="*70)
    print("✅ CRITICAL FIX: safe_compare() prevents None comparison errors")
    print("✅ Instagram → Fully None-safe parsing")
    print("✅ TikTok   → None-safe sorting")
    print("✅ Others   → Robust error handling")
    print("="*70)
    print("📡 Server: http://localhost:8000")
    print("📚 Docs: http://localhost:8000/docs")
    print("="*70)
    uvicorn.run(app, host="0.0.0.0", port=8000)