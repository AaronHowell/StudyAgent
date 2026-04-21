"""MySQL repository implementations for PaperLab."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Iterator

import pymysql
from dotenv import load_dotenv
from pymysql.cursors import DictCursor

from domain import Chunk, ChunkType, Document, DocumentAsset, DocumentStatus, DocumentType, Project


@dataclass(slots=True)
class MySQLConnectionConfig:
    """MySQL connection parameters used by repository adapters.

    作用:
        统一承载 MySQL 连接参数，避免每个 repository 单独拼接配置。

    Attributes:
        host: MySQL 主机地址。
        port: MySQL 端口。
        user: MySQL 用户名。
        password: MySQL 密码。
        database: 目标数据库名。
    """

    host: str
    port: int
    user: str
    password: str
    database: str


class MySQLRepositoryBase:
    """Shared MySQL repository helpers.

    作用:
        提供数据库连接、事务提交、JSON 序列化和表初始化等共用能力，
        避免每个 repository 重复实现同样的样板代码。
    """

    def __init__(self, config: MySQLConnectionConfig) -> None:
        """Create a repository base bound to one MySQL connection config.

        Args:
            config: MySQL 连接配置。
        """

        self.config = config

    @contextmanager
    def _connection(self) -> Iterator[pymysql.connections.Connection]:
        """Open one managed MySQL connection.

        作用:
            创建一个短生命周期数据库连接，并在退出时统一提交或回滚事务。

        Yields:
            pymysql.connections.Connection: 已打开的 MySQL 连接对象。
        """

        connection = pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            user=self.config.user,
            password=self.config.password,
            database=self.config.database,
            charset="utf8mb4",
            autocommit=False,
            cursorclass=DictCursor,
        )
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def _dump_json(value: Any) -> str:
        """Serialize one Python object into JSON text.

        Args:
            value: 任意可 JSON 序列化的对象。

        Returns:
            str: JSON 字符串。
        """

        return json.dumps(value, ensure_ascii=False)

    @staticmethod
    def _load_json(value: str | None, default: Any) -> Any:
        """Deserialize one JSON string with a default fallback.

        Args:
            value: JSON 字符串或空值。
            default: 反序列化失败时返回的默认值。

        Returns:
            Any: 解析后的 Python 对象。
        """

        if not value:
            return default
        return json.loads(value)


class MySQLProjectRepository(MySQLRepositoryBase):
    """MySQL-backed project repository.

    作用:
        负责 `projects` 表的读写，提供项目元数据的持久化能力。
    """

    def ensure_tables(self) -> None:
        """Create the `projects` table when it does not exist.

        作用:
            初始化项目元数据所需的数据表，便于本地开发和首次运行快速落库。
        """

        sql = """
        CREATE TABLE IF NOT EXISTS projects (
            id VARCHAR(64) PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            root_path TEXT NOT NULL,
            description TEXT NOT NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)

    def create(self, project: Project) -> None:
        """Insert or update one project in MySQL.

        Args:
            project: 待保存的项目对象。
        """

        sql = """
        INSERT INTO projects (id, name, root_path, description)
        VALUES (%s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            name = VALUES(name),
            root_path = VALUES(root_path),
            description = VALUES(description);
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (project.id, project.name, project.root_path, project.description))

    def get_by_id(self, project_id: str) -> Project | None:
        """Load one project by id from MySQL.

        Args:
            project_id: 项目标识。

        Returns:
            Project | None: 命中时返回项目对象，否则返回 `None`。
        """

        sql = "SELECT id, name, root_path, description FROM projects WHERE id = %s"
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (project_id,))
                row = cursor.fetchone()
        if row is None:
            return None
        return Project(
            id=row["id"],
            name=row["name"],
            root_path=row["root_path"],
            description=row["description"],
        )

    def list_all(self) -> list[Project]:
        """Load all projects from MySQL.

        Returns:
            list[Project]: 已存储的全部项目列表。
        """

        sql = "SELECT id, name, root_path, description FROM projects ORDER BY name ASC"
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                rows = cursor.fetchall()
        return [
            Project(
                id=row["id"],
                name=row["name"],
                root_path=row["root_path"],
                description=row["description"],
            )
            for row in rows
        ]

    def delete(self, project_id: str) -> None:
        """Delete one project row.

        Args:
            project_id: 项目标识。
        """

        sql = "DELETE FROM projects WHERE id = %s"
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (project_id,))


class MySQLDocumentRepository(MySQLRepositoryBase):
    """MySQL-backed document repository.

    作用:
        负责 `documents` 表的读写，持久化扫描和解析后的文档元数据。
    """

    def ensure_tables(self) -> None:
        """Create the `documents` table when it does not exist.

        作用:
            初始化文档元数据表，为后续 PDF 摄取和查询提供持久化基础。
        """

        sql = """
        CREATE TABLE IF NOT EXISTS documents (
            id VARCHAR(64) PRIMARY KEY,
            project_id VARCHAR(64) NOT NULL,
            path TEXT NOT NULL,
            file_name VARCHAR(512) NOT NULL,
            doc_type VARCHAR(32) NOT NULL,
            title TEXT NOT NULL,
            status VARCHAR(32) NOT NULL,
            content_hash VARCHAR(128) NOT NULL,
            INDEX idx_documents_project_id (project_id)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)

    def upsert(self, document: Document) -> None:
        """Insert or update one document row.

        Args:
            document: 待保存的文档对象。
        """

        sql = """
        INSERT INTO documents (id, project_id, path, file_name, doc_type, title, status, content_hash)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        ON DUPLICATE KEY UPDATE
            project_id = VALUES(project_id),
            path = VALUES(path),
            file_name = VALUES(file_name),
            doc_type = VALUES(doc_type),
            title = VALUES(title),
            status = VALUES(status),
            content_hash = VALUES(content_hash);
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    sql,
                    (
                        document.id,
                        document.project_id,
                        document.path,
                        document.file_name,
                        document.doc_type.value,
                        document.title,
                        document.status.value,
                        document.content_hash,
                    ),
                )

    def get_by_id(self, document_id: str) -> Document | None:
        """Load one document by id from MySQL.

        Args:
            document_id: 文档标识。

        Returns:
            Document | None: 命中时返回文档对象，否则返回 `None`。
        """

        sql = """
        SELECT id, project_id, path, file_name, doc_type, title, status, content_hash
        FROM documents
        WHERE id = %s
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (document_id,))
                row = cursor.fetchone()
        return self._row_to_document(row)

    def get_by_path(self, project_id: str, path: str) -> Document | None:
        """Load one document by project id and canonical path.

        Args:
            project_id: 项目标识。
            path: 规范化后的文档绝对路径。

        Returns:
            Document | None: 命中时返回文档对象，否则返回 `None`。
        """

        sql = """
        SELECT id, project_id, path, file_name, doc_type, title, status, content_hash
        FROM documents
        WHERE project_id = %s AND path = %s
        LIMIT 1
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (project_id, path))
                row = cursor.fetchone()
        return self._row_to_document(row)

    def list_by_project(self, project_id: str) -> list[Document]:
        """Load all documents for one project.

        Args:
            project_id: 项目标识。

        Returns:
            list[Document]: 当前项目下的全部文档列表。
        """

        sql = """
        SELECT id, project_id, path, file_name, doc_type, title, status, content_hash
        FROM documents
        WHERE project_id = %s
        ORDER BY title ASC
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (project_id,))
                rows = cursor.fetchall()
        return [document for row in rows if (document := self._row_to_document(row)) is not None]

    def list_by_ids(self, document_ids: list[str]) -> list[Document]:
        """Load all documents that match one id list."""

        if not document_ids:
            return []

        placeholders = ", ".join(["%s"] * len(document_ids))
        sql = f"""
        SELECT id, project_id, path, file_name, doc_type, title, status, content_hash
        FROM documents
        WHERE id IN ({placeholders})
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(document_ids))
                rows = cursor.fetchall()
        return [document for row in rows if (document := self._row_to_document(row)) is not None]

    def delete(self, document_id: str) -> None:
        """Delete one document row.

        Args:
            document_id: 文档标识。
        """

        sql = "DELETE FROM documents WHERE id = %s"
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (document_id,))

    @staticmethod
    def _row_to_document(row: dict[str, Any] | None) -> Document | None:
        """Convert one MySQL row into a `Document`.

        Args:
            row: MySQL 查询返回的行对象。

        Returns:
            Document | None: 转换后的文档对象；若传入为空则返回 `None`。
        """

        if row is None:
            return None
        return Document(
            id=row["id"],
            project_id=row["project_id"],
            path=row["path"],
            file_name=row["file_name"],
            doc_type=DocumentType(row["doc_type"]),
            title=row["title"],
            status=DocumentStatus(row["status"]),
            content_hash=row["content_hash"],
        )


class MySQLDocumentAssetRepository(MySQLRepositoryBase):
    """MySQL-backed visual asset repository.

    作用:
        负责 `document_assets` 表的读写，持久化图、表等视觉资产信息。
    """

    def ensure_tables(self) -> None:
        """Create the `document_assets` table when it does not exist.

        作用:
            初始化视觉资产表，为图、表、流程图等结构化资产提供持久化能力。
        """

        sql = """
        CREATE TABLE IF NOT EXISTS document_assets (
            id VARCHAR(64) PRIMARY KEY,
            document_id VARCHAR(64) NOT NULL,
            page_number INT NOT NULL,
            file_path TEXT NOT NULL,
            file_name VARCHAR(512) NOT NULL,
            asset_kind VARCHAR(32) NOT NULL,
            asset_label VARCHAR(255) NOT NULL,
            asset_index INT NULL,
            caption TEXT NOT NULL,
            summary TEXT NOT NULL,
            asset_type VARCHAR(64) NOT NULL,
            keywords_json JSON NOT NULL,
            related_chunk_ids_json JSON NOT NULL,
            media_type VARCHAR(64) NULL,
            metadata_json JSON NOT NULL,
            INDEX idx_document_assets_document_id (document_id),
            INDEX idx_document_assets_label (asset_label)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)

    def replace_for_document(self, document_id: str, assets: list[DocumentAsset]) -> None:
        """Replace all visual assets linked to one document.

        作用:
            先删除旧资产，再批量写入新解析出的视觉资产，保证单篇文档的资产数据一致。

        Args:
            document_id: 文档标识。
            assets: 新的视觉资产列表。
        """

        delete_sql = "DELETE FROM document_assets WHERE document_id = %s"
        insert_sql = """
        INSERT INTO document_assets (
            id, document_id, page_number, file_path, file_name, asset_kind, asset_label,
            asset_index, caption, summary, asset_type, keywords_json,
            related_chunk_ids_json, media_type, metadata_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(delete_sql, (document_id,))
                if not assets:
                    return
                cursor.executemany(
                    insert_sql,
                    [
                        (
                            asset.id,
                            asset.document_id,
                            asset.page_number,
                            asset.file_path,
                            asset.file_name,
                            asset.asset_kind,
                            asset.asset_label,
                            asset.asset_index,
                            asset.caption,
                            asset.summary,
                            asset.asset_type,
                            self._dump_json(asset.keywords),
                            self._dump_json(asset.related_chunk_ids),
                            asset.media_type,
                            self._dump_json(asset.metadata),
                        )
                        for asset in assets
                    ],
                )

    def list_by_document(self, document_id: str) -> list[DocumentAsset]:
        """Load all visual assets for one document.

        Args:
            document_id: 文档标识。

        Returns:
            list[DocumentAsset]: 该文档对应的视觉资产列表。
        """

        sql = """
        SELECT
            id, document_id, page_number, file_path, file_name, asset_kind, asset_label,
            asset_index, caption, summary, asset_type, keywords_json,
            related_chunk_ids_json, media_type, metadata_json
        FROM document_assets
        WHERE document_id = %s
        ORDER BY page_number ASC, asset_index ASC, file_name ASC
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (document_id,))
                rows = cursor.fetchall()
        return [self._row_to_asset(row) for row in rows]

    def list_by_ids(self, asset_ids: list[str]) -> list[DocumentAsset]:
        """Load all visual assets that match one id list."""

        if not asset_ids:
            return []

        placeholders = ", ".join(["%s"] * len(asset_ids))
        sql = f"""
        SELECT
            id, document_id, page_number, file_path, file_name, asset_kind, asset_label,
            asset_index, caption, summary, asset_type, keywords_json,
            related_chunk_ids_json, media_type, metadata_json
        FROM document_assets
        WHERE id IN ({placeholders})
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(asset_ids))
                rows = cursor.fetchall()
        return [self._row_to_asset(row) for row in rows]

    def delete_by_document(self, document_id: str) -> None:
        """Delete all visual assets linked to one document.

        Args:
            document_id: 文档标识。
        """

        sql = "DELETE FROM document_assets WHERE document_id = %s"
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (document_id,))

    def _row_to_asset(self, row: dict[str, Any]) -> DocumentAsset:
        """Convert one MySQL row into a `DocumentAsset`.

        Args:
            row: MySQL 查询返回的视觉资产行对象。

        Returns:
            DocumentAsset: 转换后的视觉资产对象。
        """

        return DocumentAsset(
            id=row["id"],
            document_id=row["document_id"],
            page_number=row["page_number"],
            file_path=row["file_path"],
            file_name=row["file_name"],
            asset_kind=row["asset_kind"],
            asset_label=row["asset_label"],
            asset_index=row["asset_index"],
            caption=row["caption"],
            summary=row["summary"],
            asset_type=row["asset_type"],
            keywords=self._load_json(row["keywords_json"], []),
            related_chunk_ids=self._load_json(row["related_chunk_ids_json"], []),
            media_type=row["media_type"],
            metadata=self._load_json(row["metadata_json"], {}),
        )


class MySQLChunkRepository(MySQLRepositoryBase):
    """MySQL-backed text chunk repository.

    作用:
        负责 `chunks` 表的读写，持久化文本分块和其结构化元数据。
    """

    def ensure_tables(self) -> None:
        """Create the `chunks` table when it does not exist.

        作用:
            初始化文本分块表，为后续嵌入、检索和引用提供稳定的结构化来源。
        """

        sql = """
        CREATE TABLE IF NOT EXISTS chunks (
            id VARCHAR(64) PRIMARY KEY,
            project_id VARCHAR(64) NOT NULL,
            document_id VARCHAR(64) NOT NULL,
            chunk_index INT NOT NULL,
            chunk_type VARCHAR(32) NOT NULL,
            text LONGTEXT NOT NULL,
            page INT NULL,
            section VARCHAR(255) NULL,
            metadata_json JSON NOT NULL,
            INDEX idx_chunks_document_id (document_id),
            INDEX idx_chunks_project_id (project_id),
            INDEX idx_chunks_document_order (document_id, page, chunk_index)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql)
                cursor.execute(
                    """
                    SELECT COUNT(*) AS column_count
                    FROM information_schema.columns
                    WHERE table_schema = %s
                      AND table_name = 'chunks'
                      AND column_name = 'chunk_index'
                    """,
                    (self.config.database,),
                )
                row = cursor.fetchone()
                if row is not None and int(row["column_count"]) == 0:
                    cursor.execute(
                        """
                        ALTER TABLE chunks
                        ADD COLUMN chunk_index INT NOT NULL DEFAULT 0
                        """
                    )

    def replace_for_document(self, document_id: str, chunks: list[Chunk]) -> None:
        """Replace all chunks linked to one document.

        作用:
            先删除旧 chunk，再写入最新 chunk 列表，保证单篇文档的 chunk 结果一致。

        Args:
            document_id: 文档标识。
            chunks: 新的文本分块列表。
        """

        delete_sql = "DELETE FROM chunks WHERE document_id = %s"
        insert_sql = """
        INSERT INTO chunks (
            id, project_id, document_id, chunk_index, chunk_type, text, page, section, metadata_json
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(delete_sql, (document_id,))
                if not chunks:
                    return
                cursor.executemany(
                    insert_sql,
                    [
                        (
                            chunk.id,
                            chunk.project_id,
                            chunk.document_id,
                            chunk.chunk_index,
                            chunk.chunk_type.value,
                            chunk.text,
                            chunk.page,
                            chunk.section,
                            self._dump_json(chunk.metadata),
                        )
                        for chunk in chunks
                    ],
                )

    def list_by_document(self, document_id: str) -> list[Chunk]:
        """Load all chunks for one document.

        Args:
            document_id: 文档标识。

        Returns:
            list[Chunk]: 当前文档的全部文本分块。
        """

        sql = """
        SELECT id, project_id, document_id, chunk_index, chunk_type, text, page, section, metadata_json
        FROM chunks
        WHERE document_id = %s
        ORDER BY page ASC, chunk_index ASC, id ASC
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (document_id,))
                rows = cursor.fetchall()
        return [
            Chunk(
                id=row["id"],
                project_id=row["project_id"],
                document_id=row["document_id"],
                chunk_index=row.get("chunk_index", 0),
                chunk_type=ChunkType(row["chunk_type"]),
                text=row["text"],
                page=row["page"],
                section=row["section"],
                metadata=self._load_json(row["metadata_json"], {}),
            )
            for row in rows
        ]

    def list_by_ids(self, chunk_ids: list[str]) -> list[Chunk]:
        """Load all chunks that match one id list."""

        if not chunk_ids:
            return []

        placeholders = ", ".join(["%s"] * len(chunk_ids))
        sql = f"""
        SELECT id, project_id, document_id, chunk_index, chunk_type, text, page, section, metadata_json
        FROM chunks
        WHERE id IN ({placeholders})
        """
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, tuple(chunk_ids))
                rows = cursor.fetchall()
        return [
            Chunk(
                id=row["id"],
                project_id=row["project_id"],
                document_id=row["document_id"],
                chunk_index=row.get("chunk_index", 0),
                chunk_type=ChunkType(row["chunk_type"]),
                text=row["text"],
                page=row["page"],
                section=row["section"],
                metadata=self._load_json(row["metadata_json"], {}),
            )
            for row in rows
        ]

    def delete_by_document(self, document_id: str) -> None:
        """Delete all chunks linked to one document.

        Args:
            document_id: 文档标识。
        """

        sql = "DELETE FROM chunks WHERE document_id = %s"
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.execute(sql, (document_id,))


if __name__ == "__main__":
    from uuid import uuid4

    root_env_path = Path(__file__).resolve().parents[4] / ".env"
    load_dotenv(root_env_path)

    mysql_config = MySQLConnectionConfig(
        host=os.getenv("PAPERLAB_MYSQL_HOST", "127.0.0.1"),
        port=int(os.getenv("PAPERLAB_MYSQL_PORT", "3306")),
        user=os.getenv("PAPERLAB_MYSQL_USER", "root"),
        password=os.getenv("PAPERLAB_MYSQL_PASSWORD", ""),
        database=os.getenv("PAPERLAB_MYSQL_DATABASE", "paperlab"),
    )

    project_repository = MySQLProjectRepository(mysql_config)
    document_repository = MySQLDocumentRepository(mysql_config)
    asset_repository = MySQLDocumentAssetRepository(mysql_config)
    chunk_repository = MySQLChunkRepository(mysql_config)

    project_repository.ensure_tables()
    document_repository.ensure_tables()
    asset_repository.ensure_tables()
    chunk_repository.ensure_tables()

    test_suffix = uuid4().hex[:8]
    test_project_id = f"test-project-{test_suffix}"
    test_document_id = f"test-document-{test_suffix}"
    test_asset_id = f"test-asset-{test_suffix}"
    test_chunk_id = f"test-chunk-{test_suffix}"

    test_project = Project(
        id=test_project_id,
        name="Integration Test Project",
        root_path=str(Path.cwd()),
        description="Temporary project created by mysql_repositories.py __main__",
    )
    test_document = Document(
        id=test_document_id,
        project_id=test_project_id,
        path=str(Path.cwd() / "sample.pdf"),
        file_name="sample.pdf",
        doc_type=DocumentType.PDF,
        title="Sample PDF",
        status=DocumentStatus.DISCOVERED,
        content_hash="debug-hash",
    )
    test_asset = DocumentAsset(
        id=test_asset_id,
        document_id=test_document_id,
        page_number=1,
        file_path=str(Path.cwd() / "PaperLabCache" / "sample.png"),
        file_name="sample.png",
        asset_kind="figure",
        asset_label="Figure 1",
        asset_index=1,
        caption="Figure 1: Sample caption.",
        summary="Sample figure summary for repository integration test.",
        asset_type="result_plot",
        keywords=["sample", "figure", "test"],
        related_chunk_ids=[test_chunk_id],
        media_type="image/png",
        metadata={"project_id": test_project_id, "source": "integration_test"},
    )
    test_chunk = Chunk(
        id=test_chunk_id,
        project_id=test_project_id,
        document_id=test_document_id,
        chunk_index=1,
        chunk_type=ChunkType.TEXT,
        text="This is a sample chunk used to verify MySQL repository integration.",
        page=1,
        section="Introduction",
        metadata={"source": "integration_test"},
    )

    print("Creating tables if needed...")
    print("Inserting sample rows...")
    project_repository.create(test_project)
    document_repository.upsert(test_document)
    asset_repository.replace_for_document(test_document_id, [test_asset])
    chunk_repository.replace_for_document(test_document_id, [test_chunk])

    loaded_project = project_repository.get_by_id(test_project_id)
    loaded_document = document_repository.get_by_id(test_document_id)
    loaded_assets = asset_repository.list_by_document(test_document_id)
    loaded_chunks = chunk_repository.list_by_document(test_document_id)

    print("Loaded project:", loaded_project)
    print("Loaded document:", loaded_document)
    print("Loaded assets:", len(loaded_assets))
    print("Loaded chunks:", len(loaded_chunks))

    print("Cleaning up sample rows...")
    chunk_repository.delete_by_document(test_document_id)
    asset_repository.delete_by_document(test_document_id)
    document_repository.delete(test_document_id)
    project_repository.delete(test_project_id)

    print("Cleanup completed.")




