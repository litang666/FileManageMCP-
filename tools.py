"""
tools.py - 파일 정리 MCP 서버의 도구 함수들
분석 도구와 액션 도구를 구현합니다.
"""

import os
import shutil
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field
from datetime import datetime

# 이미지 메타데이터용 (선택적)
try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from utils import (
    validate_path,
    get_file_dates,
    read_file_with_encoding,
    is_binary_file,
    get_file_size_str,
    check_directory_depth,
    validate_folder_naming,
    suggest_folder_prefix,
    sanitize_filename,
    get_target_root,
    set_target_root,
)


@dataclass
class ToolConfig:
    """도구 설정을 관리하는 클래스"""
    dry_run: bool = True  # 기본값: Dry Run 모드 활성화
    max_depth: int = 5    # 최대 디렉토리 깊이
    
    
# 전역 설정 인스턴스
config = ToolConfig()


def set_dry_run(enabled: bool) -> str:
    """
    Dry Run 모드를 설정합니다.
    
    Args:
        enabled: True면 파일 시스템을 실제로 수정하지 않음
        
    Returns:
        설정 결과 메시지
    """
    config.dry_run = enabled
    mode = "활성화" if enabled else "비활성화"
    warning = "" if enabled else "\n⚠️ 주의: 실제 파일 시스템 변경이 발생합니다!"
    return f"Dry Run 모드가 {mode}되었습니다.{warning}"


def get_dry_run_status() -> str:
    """현재 Dry Run 모드 상태를 반환합니다."""
    status = "활성화 ✓ (파일 변경 없음)" if config.dry_run else "비활성화 ⚠️ (실제 변경 발생)"
    return f"Dry Run 모드: {status}"


def configure_workspace(root_path: str) -> str:
    """
    작업 영역(샌드박스) 루트 디렉토리를 설정합니다.
    
    Args:
        root_path: 작업할 루트 디렉토리 경로
        
    Returns:
        설정 결과 메시지
    """
    path = Path(root_path)
    
    if not path.exists():
        return f"❌ 오류: 경로가 존재하지 않습니다: {root_path}"
    
    if not path.is_dir():
        return f"❌ 오류: 경로가 디렉토리가 아닙니다: {root_path}"
    
    if set_target_root(root_path):
        return f"✅ 작업 영역이 설정되었습니다: {path.resolve()}\n모든 파일 작업은 이 디렉토리 내에서만 허용됩니다."
    else:
        return f"❌ 작업 영역 설정 실패: {root_path}"


# ============================================================================
# 분석 도구 (Read-Only Tools)
# ============================================================================

def list_directory(path: str, show_hidden: bool = False) -> str:
    """
    디렉토리의 파일과 폴더를 나열합니다.
    각 항목의 생성/수정 날짜도 함께 표시합니다.
    
    Args:
        path: 탐색할 디렉토리 경로
        show_hidden: 숨김 파일/폴더 표시 여부
        
    Returns:
        디렉토리 내용 목록 (날짜 정보 포함)
    """
    validation = validate_path(path, must_exist=True)
    if not validation.is_valid:
        return f"❌ 오류: {validation.error_message}"
    
    target = validation.resolved_path
    
    if not target.is_dir():
        return f"❌ 오류: '{path}'는 디렉토리가 아닙니다."
    
    try:
        items = list(target.iterdir())
    except PermissionError:
        return f"❌ 권한 오류: '{path}'에 접근할 수 없습니다."
    
    if not show_hidden:
        items = [item for item in items if not item.name.startswith('.')]
    
    # 폴더와 파일 분리
    folders = sorted([i for i in items if i.is_dir()], key=lambda x: x.name.lower())
    files = sorted([i for i in items if i.is_file()], key=lambda x: x.name.lower())
    
    # 깊이 확인
    depth_ok, current_depth = check_directory_depth(target)
    
    result_lines = [
        f"📂 디렉토리: {target}",
        f"   현재 깊이: {current_depth}/{config.max_depth} {'✓' if depth_ok else '⚠️ 최대 깊이 초과'}",
        f"   폴더: {len(folders)}개, 파일: {len(files)}개",
        ""
    ]
    
    # 폴더 나열
    if folders:
        result_lines.append("📁 폴더:")
        for folder in folders:
            try:
                dates = get_file_dates(folder)
                is_valid, _ = validate_folder_naming(folder.name)
                naming_icon = "✓" if is_valid else "⚠"
                result_lines.append(
                    f"   [{naming_icon}] {folder.name}/ "
                    f"(생성: {dates['created_str']}, 수정: {dates['modified_str']})"
                )
            except Exception:
                result_lines.append(f"   [?] {folder.name}/")
    
    # 파일 나열
    if files:
        result_lines.append("\n📄 파일:")
        for file in files:
            try:
                dates = get_file_dates(file)
                size = get_file_size_str(file.stat().st_size)
                ext = file.suffix.lower() if file.suffix else "(없음)"
                result_lines.append(
                    f"   • {file.name}\n"
                    f"     크기: {size} | 확장자: {ext}\n"
                    f"     생성: {dates['created_str']} | 수정: {dates['modified_str']}\n"
                    f"     YYMMDD 형식 제안: {dates['modified_str']}_{file.stem}{file.suffix}"
                )
            except Exception as e:
                result_lines.append(f"   • {file.name} (정보 읽기 실패: {e})")
    
    # 폴더 번호 제안
    folder_names = [f.name for f in folders]
    next_prefix = suggest_folder_prefix(folder_names)
    result_lines.append(f"\n💡 다음 폴더 번호 제안: {next_prefix}_NewFolder")
    
    return "\n".join(result_lines)


def read_file_snippet(path: str, max_length: int = 5000) -> str:
    """
    파일의 시작 부분을 읽어 내용을 확인합니다.
    텍스트/코드 파일의 컨텍스트 파악에 유용합니다.
    
    Args:
        path: 읽을 파일 경로
        max_length: 최대 읽을 글자 수 (기본: 5000)
        
    Returns:
        파일 내용 스니펫
    """
    validation = validate_path(path, must_exist=True)
    if not validation.is_valid:
        return f"❌ 오류: {validation.error_message}"
    
    target = validation.resolved_path
    
    if not target.is_file():
        return f"❌ 오류: '{path}'는 파일이 아닙니다."
    
    # 바이너리 파일 체크
    if is_binary_file(target):
        size = get_file_size_str(target.stat().st_size)
        return f"📦 바이너리 파일입니다.\n파일명: {target.name}\n크기: {size}\n내용을 텍스트로 표시할 수 없습니다."
    
    try:
        content, encoding = read_file_with_encoding(target, max_length)
        dates = get_file_dates(target)
        
        # 내용이 잘렸는지 확인
        total_size = target.stat().st_size
        truncated = len(content) < total_size
        
        result_lines = [
            f"📄 파일: {target.name}",
            f"   경로: {target}",
            f"   크기: {get_file_size_str(total_size)}",
            f"   인코딩: {encoding}",
            f"   생성일: {dates['created_iso']}",
            f"   수정일: {dates['modified_iso']}",
            "",
            "─" * 50,
            content,
        ]
        
        if truncated:
            result_lines.append(f"\n... (파일이 너무 길어 {max_length}자까지만 표시)")
        
        result_lines.append("─" * 50)
        
        return "\n".join(result_lines)
        
    except PermissionError:
        return f"❌ 권한 오류: '{path}' 파일을 읽을 수 없습니다."
    except Exception as e:
        return f"❌ 파일 읽기 오류: {str(e)}"


def get_image_metadata(path: str) -> str:
    """
    이미지 파일의 EXIF 메타데이터를 추출합니다.
    특히 촬영 날짜 정보를 가져오는 데 유용합니다.
    
    Args:
        path: 이미지 파일 경로
        
    Returns:
        이미지 메타데이터 정보
    """
    if not PIL_AVAILABLE:
        return "❌ 오류: Pillow 라이브러리가 설치되지 않았습니다.\n'pip install Pillow' 명령으로 설치하세요."
    
    validation = validate_path(path, must_exist=True)
    if not validation.is_valid:
        return f"❌ 오류: {validation.error_message}"
    
    target = validation.resolved_path
    
    if not target.is_file():
        return f"❌ 오류: '{path}'는 파일이 아닙니다."
    
    # 이미지 확장자 확인
    image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp'}
    if target.suffix.lower() not in image_extensions:
        return f"❌ 오류: '{target.name}'은 지원되는 이미지 형식이 아닙니다."
    
    try:
        with Image.open(target) as img:
            result_lines = [
                f"🖼️ 이미지: {target.name}",
                f"   크기: {img.size[0]} x {img.size[1]} 픽셀",
                f"   포맷: {img.format}",
                f"   모드: {img.mode}",
            ]
            
            # EXIF 데이터 추출
            exif_data = img._getexif()
            if exif_data:
                result_lines.append("\n📋 EXIF 데이터:")
                
                # 관심 있는 태그들
                important_tags = {
                    'DateTimeOriginal': '촬영일시',
                    'DateTime': '날짜시간',
                    'DateTimeDigitized': '디지털화일시',
                    'Make': '제조사',
                    'Model': '모델',
                    'ImageWidth': '너비',
                    'ImageLength': '높이',
                    'Orientation': '방향',
                }
                
                date_taken = None
                
                for tag_id, value in exif_data.items():
                    tag_name = TAGS.get(tag_id, tag_id)
                    if tag_name in important_tags:
                        korean_name = important_tags[tag_name]
                        result_lines.append(f"   {korean_name}: {value}")
                        
                        # 촬영 날짜 저장
                        if tag_name == 'DateTimeOriginal':
                            date_taken = value
                
                if date_taken:
                    try:
                        # 날짜 형식: "2024:12:02 14:30:00"
                        dt = datetime.strptime(date_taken, "%Y:%m:%d %H:%M:%S")
                        yymmdd = dt.strftime("%y%m%d")
                        result_lines.append(f"\n💡 YYMMDD 형식 파일명 제안: {yymmdd}_{target.stem}{target.suffix}")
                    except Exception:
                        pass
            else:
                result_lines.append("\n⚠️ EXIF 데이터가 없습니다.")
                # 파일 시스템 날짜 사용
                dates = get_file_dates(target)
                result_lines.append(f"💡 파일 수정일 기준 제안: {dates['modified_str']}_{target.stem}{target.suffix}")
            
            return "\n".join(result_lines)
            
    except Exception as e:
        return f"❌ 이미지 읽기 오류: {str(e)}"


def analyze_directory_structure(path: str) -> str:
    """
    디렉토리 구조를 분석하고 정리 제안을 제공합니다.
    
    Args:
        path: 분석할 디렉토리 경로
        
    Returns:
        구조 분석 결과 및 정리 제안
    """
    validation = validate_path(path, must_exist=True)
    if not validation.is_valid:
        return f"❌ 오류: {validation.error_message}"
    
    target = validation.resolved_path
    
    if not target.is_dir():
        return f"❌ 오류: '{path}'는 디렉토리가 아닙니다."
    
    # 통계 수집
    stats = {
        'total_files': 0,
        'total_folders': 0,
        'extensions': {},
        'naming_issues': [],
        'depth_issues': [],
        'files_without_date': [],
    }
    
    import re
    date_pattern = re.compile(r'^\d{6}_')
    
    def scan_recursive(dir_path: Path, depth: int = 0):
        try:
            for item in dir_path.iterdir():
                if item.name.startswith('.'):
                    continue
                    
                if item.is_dir():
                    stats['total_folders'] += 1
                    
                    # 깊이 체크
                    if depth >= config.max_depth:
                        stats['depth_issues'].append(str(item))
                    
                    # 폴더 명명 규칙 체크
                    is_valid, _ = validate_folder_naming(item.name)
                    if not is_valid:
                        stats['naming_issues'].append(f"폴더: {item.name}")
                    
                    scan_recursive(item, depth + 1)
                    
                elif item.is_file():
                    stats['total_files'] += 1
                    
                    # 확장자 통계
                    ext = item.suffix.lower() if item.suffix else '(없음)'
                    stats['extensions'][ext] = stats['extensions'].get(ext, 0) + 1
                    
                    # 날짜 접두사 체크
                    if not date_pattern.match(item.name):
                        stats['files_without_date'].append(item.name)
                        
        except PermissionError:
            pass
    
    scan_recursive(target)
    
    # 결과 포맷팅
    result_lines = [
        f"📊 디렉토리 구조 분석: {target}",
        "=" * 50,
        f"\n📈 통계:",
        f"   총 파일 수: {stats['total_files']}",
        f"   총 폴더 수: {stats['total_folders']}",
    ]
    
    # 확장자별 분포
    if stats['extensions']:
        result_lines.append("\n📁 확장자별 분포:")
        sorted_exts = sorted(stats['extensions'].items(), key=lambda x: -x[1])
        for ext, count in sorted_exts[:10]:
            result_lines.append(f"   {ext}: {count}개")
    
    # 문제점
    result_lines.append("\n⚠️ 발견된 문제:")
    
    if stats['naming_issues']:
        result_lines.append(f"\n   [명명 규칙 미준수] ({len(stats['naming_issues'])}개)")
        for issue in stats['naming_issues'][:5]:
            result_lines.append(f"      • {issue}")
        if len(stats['naming_issues']) > 5:
            result_lines.append(f"      ... 외 {len(stats['naming_issues']) - 5}개")
    
    if stats['depth_issues']:
        result_lines.append(f"\n   [깊이 초과] ({len(stats['depth_issues'])}개)")
        for issue in stats['depth_issues'][:3]:
            result_lines.append(f"      • {issue}")
    
    if stats['files_without_date']:
        result_lines.append(f"\n   [날짜 접두사 없음] ({len(stats['files_without_date'])}개)")
        for file in stats['files_without_date'][:5]:
            result_lines.append(f"      • {file}")
        if len(stats['files_without_date']) > 5:
            result_lines.append(f"      ... 외 {len(stats['files_without_date']) - 5}개")
    
    if not stats['naming_issues'] and not stats['depth_issues'] and not stats['files_without_date']:
        result_lines.append("   ✅ 발견된 문제 없음!")
    
    return "\n".join(result_lines)


# ============================================================================
# 액션 도구 (File Modification Tools) - Dry Run 지원
# ============================================================================

def move_file(source: str, destination: str) -> str:
    """
    파일을 이동합니다.
    
    Args:
        source: 원본 파일 경로
        destination: 대상 경로 (파일명 포함 또는 디렉토리)
        
    Returns:
        작업 결과 메시지
    """
    # 소스 검증
    src_validation = validate_path(source, must_exist=True)
    if not src_validation.is_valid:
        return f"❌ 소스 오류: {src_validation.error_message}"
    
    src_path = src_validation.resolved_path
    
    if not src_path.is_file():
        return f"❌ 오류: '{source}'는 파일이 아닙니다."
    
    # 대상 검증
    dest_path = Path(destination).resolve()
    
    # 대상이 디렉토리면 파일명 유지
    if dest_path.exists() and dest_path.is_dir():
        dest_path = dest_path / src_path.name
    else:
        # 부모 디렉토리 존재 확인
        dest_validation = validate_path(str(dest_path.parent), must_exist=True)
        if not dest_validation.is_valid:
            return f"❌ 대상 디렉토리 오류: {dest_validation.error_message}"
    
    # 대상 경로 샌드박스 검증
    dest_validation = validate_path(str(dest_path), must_exist=False)
    if not dest_validation.is_valid:
        return f"❌ 대상 오류: {dest_validation.error_message}"
    
    # 파일 존재 확인
    if dest_path.exists():
        return f"❌ 오류: 대상에 이미 파일이 존재합니다: {dest_path}"
    
    # 깊이 체크
    depth_ok, current_depth = check_directory_depth(dest_path.parent)
    if not depth_ok:
        return f"⚠️ 경고: 대상 경로가 최대 깊이({config.max_depth})를 초과합니다. (현재: {current_depth})"
    
    # Dry Run 체크
    if config.dry_run:
        return (
            f"🔸 [Dry Run] 파일 이동 시뮬레이션:\n"
            f"   원본: {src_path}\n"
            f"   대상: {dest_path}\n"
            f"   ✓ 이동 가능합니다. 실제로 이동하려면 dry_run을 비활성화하세요."
        )
    
    # 실제 이동
    try:
        shutil.move(str(src_path), str(dest_path))
        return (
            f"✅ 파일 이동 완료:\n"
            f"   원본: {src_path}\n"
            f"   대상: {dest_path}"
        )
    except PermissionError:
        return f"❌ 권한 오류: 파일을 이동할 수 없습니다."
    except Exception as e:
        return f"❌ 이동 오류: {str(e)}"


def rename_file(path: str, new_name: str) -> str:
    """
    파일 또는 폴더의 이름을 변경합니다.
    
    Args:
        path: 대상 파일/폴더 경로
        new_name: 새 이름 (경로 없이 이름만)
        
    Returns:
        작업 결과 메시지
    """
    validation = validate_path(path, must_exist=True)
    if not validation.is_valid:
        return f"❌ 오류: {validation.error_message}"
    
    target = validation.resolved_path
    
    # 새 이름 검증
    new_name = sanitize_filename(new_name)
    if '/' in new_name or '\\' in new_name:
        return f"❌ 오류: 새 이름에는 경로 구분자를 포함할 수 없습니다."
    
    new_path = target.parent / new_name
    
    # 새 경로 검증
    new_validation = validate_path(str(new_path), must_exist=False)
    if not new_validation.is_valid:
        return f"❌ 대상 오류: {new_validation.error_message}"
    
    # 이미 존재하는지 확인
    if new_path.exists():
        return f"❌ 오류: '{new_name}'이(가) 이미 존재합니다."
    
    # 폴더인 경우 명명 규칙 확인
    if target.is_dir():
        is_valid, warning = validate_folder_naming(new_name)
        naming_msg = "" if is_valid else f"\n⚠️ 명명 규칙 경고: {warning}"
    else:
        naming_msg = ""
    
    # Dry Run 체크
    if config.dry_run:
        item_type = "폴더" if target.is_dir() else "파일"
        return (
            f"🔸 [Dry Run] {item_type} 이름 변경 시뮬레이션:\n"
            f"   현재: {target.name}\n"
            f"   변경: {new_name}\n"
            f"   경로: {target.parent}{naming_msg}\n"
            f"   ✓ 변경 가능합니다. 실제로 변경하려면 dry_run을 비활성화하세요."
        )
    
    # 실제 이름 변경
    try:
        target.rename(new_path)
        item_type = "폴더" if new_path.is_dir() else "파일"
        return (
            f"✅ {item_type} 이름 변경 완료:\n"
            f"   이전: {target.name}\n"
            f"   현재: {new_name}{naming_msg}"
        )
    except PermissionError:
        return f"❌ 권한 오류: 이름을 변경할 수 없습니다."
    except Exception as e:
        return f"❌ 이름 변경 오류: {str(e)}"


def create_folder(path: str, name: str = None) -> str:
    """
    새 폴더를 생성합니다.
    
    Args:
        path: 폴더를 생성할 위치 또는 전체 폴더 경로
        name: 폴더 이름 (선택적, path에 포함 가능)
        
    Returns:
        작업 결과 메시지
    """
    if name:
        folder_path = Path(path) / name
    else:
        folder_path = Path(path)
    
    folder_path = folder_path.resolve()
    
    # 부모 디렉토리 검증
    parent_validation = validate_path(str(folder_path.parent), must_exist=True)
    if not parent_validation.is_valid:
        return f"❌ 부모 디렉토리 오류: {parent_validation.error_message}"
    
    # 새 경로 검증
    folder_validation = validate_path(str(folder_path), must_exist=False)
    if not folder_validation.is_valid:
        return f"❌ 경로 오류: {folder_validation.error_message}"
    
    # 이미 존재하는지 확인
    if folder_path.exists():
        return f"❌ 오류: '{folder_path}'이(가) 이미 존재합니다."
    
    # 깊이 체크
    depth_ok, current_depth = check_directory_depth(folder_path)
    if not depth_ok:
        return f"❌ 오류: 최대 디렉토리 깊이({config.max_depth})를 초과합니다. (결과 깊이: {current_depth})"
    
    # 명명 규칙 확인
    folder_name = folder_path.name
    is_valid, warning = validate_folder_naming(folder_name)
    naming_msg = "" if is_valid else f"\n⚠️ 명명 규칙 경고: {warning}"
    
    # Dry Run 체크
    if config.dry_run:
        return (
            f"🔸 [Dry Run] 폴더 생성 시뮬레이션:\n"
            f"   경로: {folder_path}\n"
            f"   깊이: {current_depth}/{config.max_depth}{naming_msg}\n"
            f"   ✓ 생성 가능합니다. 실제로 생성하려면 dry_run을 비활성화하세요."
        )
    
    # 실제 폴더 생성
    try:
        folder_path.mkdir(parents=False, exist_ok=False)
        return (
            f"✅ 폴더 생성 완료:\n"
            f"   경로: {folder_path}\n"
            f"   깊이: {current_depth}/{config.max_depth}{naming_msg}"
        )
    except PermissionError:
        return f"❌ 권한 오류: 폴더를 생성할 수 없습니다."
    except FileExistsError:
        return f"❌ 오류: 폴더가 이미 존재합니다."
    except Exception as e:
        return f"❌ 폴더 생성 오류: {str(e)}"


def batch_rename_with_date(directory: str, use_modified: bool = True) -> str:
    """
    디렉토리 내 모든 파일에 YYMMDD 날짜 접두사를 추가합니다.
    
    Args:
        directory: 대상 디렉토리 경로
        use_modified: True면 수정일, False면 생성일 사용
        
    Returns:
        작업 결과 (또는 Dry Run 시뮬레이션)
    """
    import re
    
    validation = validate_path(directory, must_exist=True)
    if not validation.is_valid:
        return f"❌ 오류: {validation.error_message}"
    
    target = validation.resolved_path
    
    if not target.is_dir():
        return f"❌ 오류: '{directory}'는 디렉토리가 아닙니다."
    
    date_pattern = re.compile(r'^\d{6}_')
    changes = []
    
    try:
        for item in target.iterdir():
            if not item.is_file():
                continue
            if item.name.startswith('.'):
                continue
            
            # 이미 날짜 접두사가 있는 파일은 건너뜀
            if date_pattern.match(item.name):
                continue
            
            dates = get_file_dates(item)
            date_str = dates['modified_str'] if use_modified else dates['created_str']
            new_name = f"{date_str}_{item.name}"
            
            changes.append({
                'old': item.name,
                'new': new_name,
                'path': item
            })
    except PermissionError:
        return f"❌ 권한 오류: 디렉토리에 접근할 수 없습니다."
    
    if not changes:
        return "ℹ️ 이름을 변경할 파일이 없습니다. (모든 파일에 이미 날짜 접두사가 있음)"
    
    date_type = "수정일" if use_modified else "생성일"
    
    if config.dry_run:
        result_lines = [
            f"🔸 [Dry Run] 일괄 날짜 접두사 추가 시뮬레이션 ({date_type} 기준):",
            f"   대상 디렉토리: {target}",
            f"   변경 예정 파일: {len(changes)}개",
            ""
        ]
        for change in changes[:10]:
            result_lines.append(f"   • {change['old']}")
            result_lines.append(f"     → {change['new']}")
        
        if len(changes) > 10:
            result_lines.append(f"   ... 외 {len(changes) - 10}개 파일")
        
        result_lines.append("\n✓ 실제로 변경하려면 dry_run을 비활성화하세요.")
        return "\n".join(result_lines)
    
    # 실제 이름 변경
    success = 0
    errors = []
    
    for change in changes:
        try:
            new_path = change['path'].parent / change['new']
            change['path'].rename(new_path)
            success += 1
        except Exception as e:
            errors.append(f"{change['old']}: {str(e)}")
    
    result_lines = [
        f"✅ 일괄 날짜 접두사 추가 완료 ({date_type} 기준):",
        f"   성공: {success}개",
        f"   실패: {len(errors)}개"
    ]
    
    if errors:
        result_lines.append("\n❌ 오류 목록:")
        for error in errors[:5]:
            result_lines.append(f"   • {error}")
    
    return "\n".join(result_lines)

