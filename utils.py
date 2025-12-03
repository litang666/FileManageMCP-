"""
utils.py - 파일 정리 MCP 서버용 유틸리티 함수
경로 검증, 인코딩 처리, 안전성 검사 등을 담당합니다.
"""

import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Tuple
from dataclasses import dataclass


@dataclass
class PathValidationResult:
    """경로 검증 결과를 담는 데이터 클래스"""
    is_valid: bool
    error_message: Optional[str] = None
    resolved_path: Optional[Path] = None


# 접근 금지 폴더 목록 (Windows 시스템 폴더)
FORBIDDEN_PATHS = [
    "Windows",
    "Program Files",
    "Program Files (x86)",
    "ProgramData",
    "System32",
    "SysWOW64",
    "$Recycle.Bin",
    "Recovery",
    ".git",
    ".svn",
    "__pycache__",
    "node_modules",
]

# 접근 금지 드라이브 경로 패턴
FORBIDDEN_DRIVE_PATHS = [
    r"C:\\Windows",
    r"C:\\Program Files",
    r"C:\\Program Files (x86)",
    r"C:\\ProgramData",
]


def get_target_root() -> Optional[Path]:
    """
    환경 변수에서 타겟 루트 디렉토리를 가져옵니다.
    설정되지 않은 경우 None을 반환합니다.
    """
    root = os.environ.get("MCP_FILE_AGENT_ROOT")
    if root:
        return Path(root).resolve()
    return None


def set_target_root(path: str) -> bool:
    """
    타겟 루트 디렉토리를 설정합니다.
    반환값: 성공 여부
    """
    try:
        resolved = Path(path).resolve()
        if resolved.exists() and resolved.is_dir():
            os.environ["MCP_FILE_AGENT_ROOT"] = str(resolved)
            return True
        return False
    except Exception:
        return False


def is_path_in_sandbox(path: Path, root: Path) -> bool:
    """
    주어진 경로가 샌드박스(루트 디렉토리) 내에 있는지 확인합니다.
    """
    try:
        resolved_path = path.resolve()
        resolved_root = root.resolve()
        # 경로가 루트로 시작하는지 확인
        return str(resolved_path).startswith(str(resolved_root))
    except Exception:
        return False


def is_forbidden_path(path: Path) -> Tuple[bool, Optional[str]]:
    """
    접근 금지된 시스템 경로인지 확인합니다.
    반환: (금지 여부, 이유)
    """
    path_str = str(path.resolve())
    path_parts = path.parts
    
    # 시스템 드라이브 경로 체크
    for forbidden in FORBIDDEN_DRIVE_PATHS:
        if path_str.lower().startswith(forbidden.lower()):
            return True, f"시스템 폴더 접근 금지: {forbidden}"
    
    # 폴더 이름 체크
    for part in path_parts:
        if part in FORBIDDEN_PATHS:
            return True, f"금지된 폴더 접근: {part}"
    
    return False, None


def validate_path(path: str, must_exist: bool = True) -> PathValidationResult:
    """
    경로를 검증하고 안전한지 확인합니다.
    
    Args:
        path: 검증할 경로
        must_exist: True일 경우 경로가 존재해야 함
        
    Returns:
        PathValidationResult 객체
    """
    try:
        # 경로 정규화
        resolved = Path(path).resolve()
        
        # 금지된 경로 체크
        is_forbidden, reason = is_forbidden_path(resolved)
        if is_forbidden:
            return PathValidationResult(
                is_valid=False,
                error_message=reason
            )
        
        # 타겟 루트 확인
        root = get_target_root()
        if root and not is_path_in_sandbox(resolved, root):
            return PathValidationResult(
                is_valid=False,
                error_message=f"경로가 허용된 작업 영역 외부에 있습니다: {resolved}\n허용된 루트: {root}"
            )
        
        # 존재 여부 확인
        if must_exist and not resolved.exists():
            return PathValidationResult(
                is_valid=False,
                error_message=f"경로가 존재하지 않습니다: {resolved}"
            )
        
        return PathValidationResult(
            is_valid=True,
            resolved_path=resolved
        )
        
    except Exception as e:
        return PathValidationResult(
            is_valid=False,
            error_message=f"경로 검증 오류: {str(e)}"
        )


def check_directory_depth(path: Path, max_depth: int = 5) -> Tuple[bool, int]:
    """
    디렉토리 깊이가 최대 제한을 초과하는지 확인합니다.
    
    Args:
        path: 확인할 경로
        max_depth: 최대 허용 깊이 (기본값: 5)
        
    Returns:
        (규칙 준수 여부, 현재 깊이)
    """
    root = get_target_root()
    if not root:
        return True, 0
    
    try:
        resolved = path.resolve()
        relative = resolved.relative_to(root)
        depth = len(relative.parts)
        return depth <= max_depth, depth
    except ValueError:
        # root 외부 경로
        return True, 0


def read_file_with_encoding(
    path: Path, 
    max_length: int = 5000
) -> Tuple[str, str]:
    """
    파일을 여러 인코딩으로 시도하여 읽습니다.
    Windows 환경에서 흔한 cp949/euc-kr도 지원합니다.
    
    Args:
        path: 읽을 파일 경로
        max_length: 최대 읽을 글자 수
        
    Returns:
        (파일 내용, 사용된 인코딩)
    """
    encodings = ['utf-8', 'utf-8-sig', 'cp949', 'euc-kr', 'latin-1']
    
    for encoding in encodings:
        try:
            with open(path, 'r', encoding=encoding) as f:
                content = f.read(max_length)
                return content, encoding
        except UnicodeDecodeError:
            continue
        except Exception as e:
            raise e
    
    # 모든 인코딩 실패 시 바이너리로 읽고 대체 문자 사용
    with open(path, 'rb') as f:
        raw = f.read(max_length)
        return raw.decode('utf-8', errors='replace'), 'binary (fallback)'


def get_file_dates(path: Path) -> dict:
    """
    파일의 날짜 정보를 가져옵니다.
    
    Returns:
        {
            'created': datetime,
            'modified': datetime,
            'accessed': datetime,
            'created_str': 'YYMMDD' 형식,
            'modified_str': 'YYMMDD' 형식
        }
    """
    stat = path.stat()
    
    # Windows에서 st_ctime은 생성 시간
    created = datetime.fromtimestamp(stat.st_ctime)
    modified = datetime.fromtimestamp(stat.st_mtime)
    accessed = datetime.fromtimestamp(stat.st_atime)
    
    return {
        'created': created,
        'modified': modified,
        'accessed': accessed,
        'created_str': created.strftime('%y%m%d'),
        'modified_str': modified.strftime('%y%m%d'),
        'created_iso': created.isoformat(),
        'modified_iso': modified.isoformat(),
    }


def format_filename_with_date(
    original_name: str, 
    date: datetime,
    prefix_date: bool = True
) -> str:
    """
    파일명에 날짜 접두사를 추가합니다.
    
    Args:
        original_name: 원본 파일명
        date: 사용할 날짜
        prefix_date: True면 YYMMDD_ 접두사 추가
        
    Returns:
        새 파일명 (예: '251202_report.docx')
    """
    if not prefix_date:
        return original_name
    
    date_str = date.strftime('%y%m%d')
    
    # 이미 날짜 접두사가 있는지 확인
    date_pattern = re.compile(r'^\d{6}_')
    if date_pattern.match(original_name):
        # 기존 날짜 교체
        return date_pattern.sub(f'{date_str}_', original_name)
    
    return f'{date_str}_{original_name}'


def validate_folder_naming(name: str) -> Tuple[bool, Optional[str]]:
    """
    폴더 명명 규칙(00~99 접두사)을 확인합니다.
    
    Returns:
        (규칙 준수 여부, 오류 메시지)
    """
    pattern = re.compile(r'^(\d{2})_(.+)$')
    match = pattern.match(name)
    
    if not match:
        return False, "폴더 이름은 'NN_이름' 형식이어야 합니다 (예: 01_Project)"
    
    number = int(match.group(1))
    if number < 0 or number > 99:
        return False, "폴더 번호는 00~99 사이여야 합니다"
    
    return True, None


def suggest_folder_prefix(existing_folders: list[str]) -> str:
    """
    기존 폴더들을 분석하여 다음 사용할 번호를 제안합니다.
    
    Returns:
        제안 접두사 (예: '05')
    """
    pattern = re.compile(r'^(\d{2})_')
    used_numbers = set()
    
    for folder in existing_folders:
        match = pattern.match(folder)
        if match:
            used_numbers.add(int(match.group(1)))
    
    # 다음 사용 가능한 번호 찾기 (99는 Archive 용으로 예약)
    for i in range(1, 99):
        if i not in used_numbers:
            return f'{i:02d}'
    
    return '98'  # fallback


def is_binary_file(path: Path) -> bool:
    """
    파일이 바이너리인지 텍스트인지 추정합니다.
    """
    try:
        with open(path, 'rb') as f:
            chunk = f.read(8192)
            # NULL 바이트가 있으면 바이너리로 간주
            if b'\x00' in chunk:
                return True
            
            # 대부분의 바이트가 텍스트 범위 내인지 확인
            text_chars = bytearray({7, 8, 9, 10, 12, 13, 27} | set(range(0x20, 0x100)) - {0x7f})
            non_text = sum(1 for byte in chunk if byte not in text_chars)
            return non_text / len(chunk) > 0.3 if chunk else False
    except Exception:
        return True


def get_file_size_str(size_bytes: int) -> str:
    """
    바이트 크기를 읽기 쉬운 문자열로 변환합니다.
    """
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def sanitize_filename(filename: str) -> str:
    """
    파일명에서 불법 문자를 제거합니다.
    """
    # Windows에서 사용할 수 없는 문자들
    illegal_chars = r'<>:"/\|?*'
    for char in illegal_chars:
        filename = filename.replace(char, '_')
    
    # 앞뒤 공백 및 점 제거
    filename = filename.strip(' .')
    
    # 빈 문자열 방지
    if not filename:
        filename = 'unnamed'
    
    return filename

