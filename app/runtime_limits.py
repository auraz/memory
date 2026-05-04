import logging
import resource


def raise_file_descriptor_limit(target: int = 65536) -> tuple[int, int]:
    """Raise this process' open-file soft limit for local vector stores."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    new_soft = min(max(soft, target), hard)
    if new_soft != soft:
        resource.setrlimit(resource.RLIMIT_NOFILE, (new_soft, hard))
        logging.info("Raised RLIMIT_NOFILE from %s to %s", soft, new_soft)
    return resource.getrlimit(resource.RLIMIT_NOFILE)
