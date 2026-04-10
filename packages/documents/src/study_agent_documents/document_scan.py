"""Class-based document discovery for local project folders.

This module now uses a class-oriented design so future API integration can hold
scanner configuration and dependencies on an object instance.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from hashlib import sha256
import json
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

from study_agent_documents.pdf_parser import PdfParser
from study_agent_domain import (
    Document,
    DocumentDiscoveryResult,
    DocumentStatus,
    DocumentType,
    Project,
    ScanStatus,
    ScanSummary,
)


SUPPORTED_DOCUMENT_SUFFIXES: dict[str, DocumentType] = {
    ".pdf": DocumentType.PDF,
    ".md": DocumentType.MARKDOWN,
}

DEFAULT_IGNORED_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".idea",
    ".vscode",
    ".venv",
    "node_modules",
    "dist",
    "build",
}


@dataclass(slots=True)
class DocumentScanOptions:
    """Configuration held by one scanner instance.

    作用:
        集中保存文档扫描所需的规则配置，避免把扫描参数分散到每次方法调用中。

    Attributes:
        ignored_dir_names: 扫描时需要忽略的目录名集合，会统一按小写比较。
        include_hidden: 是否允许扫描隐藏路径。
        supported_suffixes: 当前允许识别的文档后缀到 `DocumentType` 的映射。
    """

    ignored_dir_names: set[str] = field(
        default_factory=lambda: {name.lower() for name in DEFAULT_IGNORED_DIR_NAMES}
    )
    include_hidden: bool = False
    supported_suffixes: dict[str, DocumentType] = field(
        default_factory=lambda: dict(SUPPORTED_DOCUMENT_SUFFIXES)
    )

    @classmethod
    def with_defaults(cls) -> "DocumentScanOptions":
        """Build a scanner options object with the project defaults.

        Returns:
            DocumentScanOptions: 使用默认忽略目录和默认文档后缀的配置对象。
        """

        return cls()


class LocalDocumentScanner:
    """Scan a local project folder and build lightweight document records.

    作用:
        封装本地目录扫描逻辑，发现支持的文档，并将文件系统中的文档转换为
        系统内部使用的 `Document` 记录。
    """

    def __init__(
        self,
        options: DocumentScanOptions | None = None,
        pdf_parser: PdfParser | None = None,
    ) -> None:
        self.options = options or DocumentScanOptions.with_defaults()
        self.pdf_parser = pdf_parser or PdfParser()

    def normalize_ignored_dir_names(self) -> set[str]:
        """Normalize ignored directory names for comparisons.

        作用:
            将忽略目录名统一转换为小写并去掉空白，保证路径比较稳定。

        Returns:
            set[str]: 规范化后的忽略目录名集合。
        """

        return {name.strip().lower() for name in self.options.ignored_dir_names if name.strip()}

    def is_hidden_path(self, path: Path) -> bool:
        """Return whether a path should be treated as hidden during scanning.

        作用:
            判断一个路径是否属于隐藏路径。当前只按“点前缀路径”规则处理，
            例如 `.git`、`.venv`、`.cache`。

        Args:
            path: 需要判断的路径对象。

        Returns:
            bool: 如果路径任一层级以 `.` 开头，则返回 `True`。
        """

        return any(part.startswith(".") for part in path.parts)

    def detect_document_type(self, path: Path) -> DocumentType | None:
        """Map a file path to the current supported `DocumentType`.

        作用:
            根据文件后缀识别当前支持的文档类型。

        Args:
            path: 待识别的文件路径。

        Returns:
            DocumentType | None: 支持时返回文档类型，不支持时返回 `None`。
        """

        return self.options.supported_suffixes.get(path.suffix.lower())

    def should_include_path(self, path: Path) -> bool:
        """Decide whether a path should be included in the current scan.

        作用:
            根据扫描配置判断一个路径是否应该进入本轮文档发现结果。

        Args:
            path: 待检查的路径对象。

        Returns:
            bool: 满足扫描条件时返回 `True`，否则返回 `False`。
        """

        normalized_ignored_dir_names = self.normalize_ignored_dir_names()

        if not path.is_file():
            return False
        if not self.options.include_hidden and self.is_hidden_path(path):
            return False
        if any(part.lower() in normalized_ignored_dir_names for part in path.parts):
            return False
        return path.suffix.lower() in self.options.supported_suffixes

    def validate_project_root(self, project_root: Path) -> Path:
        """Validate and normalize a project root before scanning.

        作用:
            在真正扫描前校验项目目录是否存在且为目录，并返回规范化后的绝对路径。

        Args:
            project_root: 项目根目录路径。

        Returns:
            Path: 规范化后的项目根目录绝对路径。

        Raises:
            FileNotFoundError: 当目录不存在时抛出。
            NotADirectoryError: 当路径存在但不是目录时抛出。
        """

        resolved_root = project_root.expanduser().resolve()
        if not resolved_root.exists():
            raise FileNotFoundError(f"Project root does not exist: {resolved_root}")
        if not resolved_root.is_dir():
            raise NotADirectoryError(f"Project root is not a directory: {resolved_root}")
        return resolved_root

    def scan_project_documents(self, project_root: Path) -> list[Path]:
        """Return all supported document paths inside a project root.

        作用:
            递归扫描项目目录，返回所有符合当前规则的文档路径。

        Args:
            project_root: 需要扫描的项目根目录。

        Returns:
            list[Path]: 按稳定顺序排序后的文档绝对路径列表。

        Raises:
            FileNotFoundError: 当项目目录不存在时抛出。
            NotADirectoryError: 当项目路径不是目录时抛出。
        """

        resolved_root = self.validate_project_root(project_root)
        discovered_paths: list[Path] = []

        for path in resolved_root.rglob("*"):
            if self.should_include_path(path):
                discovered_paths.append(path.resolve())

        return sorted(discovered_paths)

    def compute_content_hash(self, path: Path) -> str:
        """Compute a stable file hash for change detection.

        作用:
            为文件生成稳定的 SHA-256 摘要，后续可以用于变更检测和去重。

        Args:
            path: 需要计算哈希值的文件路径。

        Returns:
            str: 文件内容的十六进制哈希字符串。
        """

        hasher = sha256()
        with path.open("rb") as file_handle:
            for chunk in iter(lambda: file_handle.read(1024 * 1024), b""):
                hasher.update(chunk)
        return hasher.hexdigest()

    def build_document_title(self, path: Path) -> str:
        """Build a human-friendly title from a file path.

        作用:
            优先根据文档内容或元数据生成标题；如果无法提取，再回退到文件名。

        Args:
            path: 文档文件路径。

        Returns:
            str: 生成的默认文档标题。
        """

        document_type = self.detect_document_type(path)

        if document_type == DocumentType.PDF:
            try:
                metadata = self.pdf_parser.parse_pdf_metadata(path)
            except Exception:
                metadata = {}

            candidate_title = str(metadata.get("title") or "").strip()
            if candidate_title:
                return candidate_title

        return path.stem.strip() or path.name

    def build_document_record(self, project_id: str, path: Path) -> Document:
        """Create a lightweight `Document` record from a discovered file.

        作用:
            将一个已经发现的文件路径转换为系统内部的 `Document` 记录。

        Args:
            project_id: 所属项目的标识符。
            path: 已发现的文档路径。

        Returns:
            Document: 构建完成的文档对象。

        Raises:
            ValueError: 当文件类型不受支持时抛出。
        """

        document_type = self.detect_document_type(path)
        if document_type is None:
            raise ValueError(f"Unsupported document type for path: {path}")

        normalized_path = path.resolve()
        document_id = str(uuid5(NAMESPACE_URL, f"{project_id}:{normalized_path.as_posix()}"))

        return Document(
            id=document_id,
            project_id=project_id,
            path=str(normalized_path),
            file_name=normalized_path.name,
            doc_type=document_type,
            title=self.build_document_title(normalized_path),
            status=DocumentStatus.DISCOVERED,
            content_hash=self.compute_content_hash(normalized_path),
        )

    def build_skip_result(self, path: Path, reason: str) -> DocumentDiscoveryResult:
        """Create a standardized skip result row for scan summaries.

        Args:
            path: 被跳过的路径。
            reason: 跳过原因。

        Returns:
            DocumentDiscoveryResult: 标准化的跳过结果对象。
        """

        return DocumentDiscoveryResult(
            path=str(path),
            status=ScanStatus.SKIPPED,
            reason=reason,
        )

    def build_error_result(self, path: Path, reason: str) -> DocumentDiscoveryResult:
        """Create a standardized error result row for scan summaries.

        Args:
            path: 出错的路径。
            reason: 错误原因。

        Returns:
            DocumentDiscoveryResult: 标准化的错误结果对象。
        """

        return DocumentDiscoveryResult(
            path=str(path),
            status=ScanStatus.ERROR,
            reason=reason,
        )

    def scan_project(self, project: Project) -> ScanSummary:
        """Scan one project root and return a structured discovery summary.

        作用:
            作为扫描器主入口，完成项目目录校验、文档发现、文档记录构建和结果汇总。

        Args:
            project: 需要扫描的项目对象。

        Returns:
            ScanSummary: 包含发现文档、逐文件结果和统计信息的扫描摘要。

        Raises:
            FileNotFoundError: 当项目目录不存在时抛出。
            NotADirectoryError: 当项目路径不是目录时抛出。
        """

        project_root = self.validate_project_root(Path(project.root_path))
        summary = ScanSummary(project_id=project.id)

        for path in self.scan_project_documents(project_root):
            try:
                document = self.build_document_record(project.id, path)
            except Exception as exc:
                # 不让单个文件失败拖垮整个项目扫描。
                summary.results.append(self.build_error_result(path, str(exc)))
                continue

            summary.discovered_documents.append(document)
            summary.results.append(
                DocumentDiscoveryResult(
                    path=str(path),
                    status=ScanStatus.DISCOVERED,
                    document=document,
                )
            )

        return summary

    def serialize_scan_summary(self, summary: ScanSummary) -> dict[str, object]:
        """Convert a `ScanSummary` dataclass tree into JSON-friendly data.

        作用:
            将 dataclass 形式的扫描摘要转换为可直接 JSON 序列化的字典。

        Args:
            summary: 扫描结果摘要对象。

        Returns:
            dict[str, object]: 适合打印、日志记录或 API 返回的字典结果。
        """

        data = asdict(summary)
        data["discovered_count"] = summary.discovered_count
        data["skipped_count"] = summary.skipped_count
        data["error_count"] = summary.error_count
        return data


if __name__ == "__main__":
    import sys

    target_root = Path(r"C:\Users\Aaron_Howell\Desktop\postgraduate\PaperStore").expanduser()

    example_project = Project(
        id="example-project",
        name="Example Project",
        root_path=str(target_root),
        description="Ad-hoc project used for local scan testing.",
    )

    scanner = LocalDocumentScanner()
    scan_summary = scanner.scan_project(example_project)
    print(json.dumps(scanner.serialize_scan_summary(scan_summary), indent=2, ensure_ascii=False))
