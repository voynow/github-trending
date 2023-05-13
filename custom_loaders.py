import concurrent.futures
import os
from typing import Callable, List, Optional

from langchain.docstore.document import Document
from langchain.document_loaders.base import BaseLoader


class FastGitLoader(BaseLoader):
    """
    Code from https://github.com/hwchase17/langchain/blob/master/langchain/document_loaders/git.py
    Slight modifications to filter in order to speed up loading
    """

    def __init__(
        self,
        repo_path: str,
        clone_url: Optional[str] = None,
        branch: Optional[str] = "main",
        file_filter: Optional[Callable[[str], bool]] = None,
    ):
        self.repo_path = repo_path
        self.clone_url = clone_url
        self.branch = branch
        self.file_filter = file_filter

    def load(self) -> List[Document]:
        try:
            from git import Blob, Repo  # type: ignore
        except ImportError as ex:
            raise ImportError(
                "Could not import git python package. "
                "Please install it with `pip install GitPython`."
            ) from ex

        if not os.path.exists(self.repo_path) and self.clone_url is None:
            raise ValueError(f"Path {self.repo_path} does not exist")
        elif self.clone_url:
            repo = Repo.clone_from(self.clone_url, self.repo_path)
            repo.git.checkout(self.branch)
        else:
            repo = Repo(self.repo_path)
            repo.git.checkout(self.branch)

        docs: List[Document] = []

        for item in repo.tree().traverse():
            if not isinstance(item, Blob):
                continue

            file_path = os.path.join(self.repo_path, item.path)

            # uses filter to skip files
            if self.file_filter and not self.file_filter(file_path):
                continue

            ignored_files = repo.ignored([file_path])  # type: ignore
            if len(ignored_files):
                continue

            rel_file_path = os.path.relpath(file_path, self.repo_path)
            try:
                with open(file_path, "rb") as f:
                    content = f.read()
                    file_type = os.path.splitext(item.name)[1]

                    # loads only text files
                    try:
                        text_content = content.decode("utf-8")
                    except UnicodeDecodeError:
                        continue

                    metadata = {
                        "file_path": rel_file_path,
                        "file_name": item.name,
                        "file_type": file_type,
                    }
                    doc = Document(page_content=text_content, metadata=metadata)
                    docs.append(doc)
            except Exception as e:
                print(f"Error reading file {file_path}: {e}")

        return docs


class TurboGitLoader(BaseLoader):
    """
    Loads files from a Git repository into a list of documents in parallel.

    Credit to GPT4.
    """

    def __init__(
        self,
        repo_path: str,
        clone_url: Optional[str] = None,
        branch: Optional[str] = "main",
        file_filter: Optional[Callable[[str], bool]] = None,
    ):
        """Initializes the loader with the given parameters.

        Parameters:
            repo_path: The path to the repository.
            clone_url: The URL to clone the repository from, if it's not local.
            branch: The branch to load the files from.
            file_filter: A function to filter the files to load.
        """
        self.repo_path = repo_path
        self.clone_url = clone_url
        self.branch = branch
        self.file_filter = file_filter

    def _load_file(self, item) -> Optional[Document]:
        """Loads a single file from the repository.

        Parameters:
            item: The item to load.

        Returns:
            The document, or None if the file could not be loaded.
        """
        from git import Blob  # type: ignore

        if not isinstance(item, Blob):
            return None

        file_path = os.path.join(self.repo_path, item.path)

        # uses filter to skip files
        if self.file_filter and not self.file_filter(file_path):
            return None

        rel_file_path = os.path.relpath(file_path, self.repo_path)
        try:
            with open(file_path, "rb") as f:
                content = f.read()
                file_type = os.path.splitext(item.name)[1]

                # loads only text files
                try:
                    text_content = content.decode("utf-8")
                except UnicodeDecodeError:
                    return None

                metadata = {
                    "file_path": rel_file_path,
                    "file_name": item.name,
                    "file_type": file_type,
                }
                doc = Document(page_content=text_content, metadata=metadata)
                return doc
        except Exception as e:
            print(f"Error reading file {file_path}: {e}")
            return None

    def load(self) -> List[Document]:
        """Loads all files from the repository in parallel.

        Returns:
            The list of documents.
        """
        from git import Repo  # type: ignore

        if not os.path.exists(self.repo_path) and self.clone_url is None:
            raise ValueError(f"Path {self.repo_path} does not exist")
        elif self.clone_url:
            repo = Repo.clone_from(self.clone_url, self.repo_path)
            repo.git.checkout(self.branch)
        else:
            repo = Repo(self.repo_path)
            repo.git.checkout(self.branch)

        docs: List[Document] = []

        # Use a ThreadPoolExecutor to load files in parallel
        with concurrent.futures.ThreadPoolExecutor() as executor:
            future_to_item = {executor.submit(self._load_file, item): item for item in repo.tree().traverse()}
            for future in concurrent.futures.as_completed(future_to_item):
                doc = future.result()
                if doc is not None:
                    docs.append(doc)

        return docs
