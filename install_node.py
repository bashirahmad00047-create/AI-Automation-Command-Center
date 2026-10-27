"""
Automatic Node.js & npm Environment Provisioner for Render & Cloud Hosts.
Ensures that `node` and `npm` are always available in the Python runtime
without requiring root or apt-get privileges.
"""
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request


def ensure_node_installed():
    """Checks for node and npm. If missing, installs prebuilt Node.js into the environment."""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    venv_bin = os.path.dirname(sys.executable)

    # 1. Check if node and npm are already in PATH
    node_path = shutil.which("node")
    npm_path = shutil.which("npm.cmd" if sys.platform == "win32" else "npm")
    if node_path and npm_path:
        print(f"[Node Provisioner] Node already found in PATH: {node_path}", flush=True)
        return True

    # 2. Check virtual environment bin directory
    venv_node = os.path.join(venv_bin, "node.exe" if sys.platform == "win32" else "node")
    venv_npm = os.path.join(venv_bin, "npm.cmd" if sys.platform == "win32" else "npm")
    if os.path.exists(venv_node) and os.path.exists(venv_npm):
        print(f"[Node Provisioner] Found Node in virtualenv: {venv_node}", flush=True)
        if venv_bin not in os.environ.get("PATH", "").split(os.pathsep):
            os.environ["PATH"] = venv_bin + os.pathsep + os.environ.get("PATH", "")
        return True

    # 3. Check project .node directory
    local_node_bin = os.path.join(root_dir, ".node", "bin")
    if os.path.exists(os.path.join(local_node_bin, "node")):
        print(f"[Node Provisioner] Found portable Node in {local_node_bin}", flush=True)
        os.environ["PATH"] = local_node_bin + os.pathsep + os.environ.get("PATH", "")
        return True

    print("[Node Provisioner] Node.js not detected. Installing prebuilt Node for cloud runtime...", flush=True)

    # 4. Attempt nodeenv first if on Linux / cloud
    try:
        import nodeenv
        print("[Node Provisioner] Provisioning prebuilt Node via nodeenv...", flush=True)
        res = subprocess.run([sys.executable, "-m", "nodeenv", "-p", "--prebuilt"], capture_output=True, text=True)
        if res.returncode == 0:
            print("[Node Provisioner] nodeenv installation succeeded!", flush=True)
            return True
        else:
            print(f"[Node Provisioner] nodeenv output: {res.stderr or res.stdout}", flush=True)
    except Exception as e:
        print(f"[Node Provisioner] nodeenv notice: {e}", flush=True)

    # 5. Direct standalone portable Node.js download for Linux x64 (Render standard image)
    if sys.platform.startswith("linux"):
        try:
            node_version = "v20.18.0"
            tar_name = f"node-{node_version}-linux-x64.tar.gz"
            url = f"https://nodejs.org/dist/{node_version}/{tar_name}"
            tmp_tar = os.path.join("/tmp", tar_name)
            
            print(f"[Node Provisioner] Downloading official {url}...", flush=True)
            urllib.request.urlretrieve(url, tmp_tar)
            
            extract_dir = os.path.join(root_dir, ".node")
            os.makedirs(extract_dir, exist_ok=True)
            with tarfile.open(tmp_tar, "r:gz") as tar:
                tar.extractall(extract_dir)
            
            extracted_bin = os.path.join(extract_dir, f"node-{node_version}-linux-x64", "bin")
            if os.path.exists(extracted_bin):
                # Copy or symlink binaries into venv_bin so they persist in PATH
                for b in ["node", "npm", "npx"]:
                    src = os.path.join(extracted_bin, b)
                    dst = os.path.join(venv_bin, b)
                    if os.path.exists(src) and not os.path.exists(dst):
                        try:
                            os.symlink(src, dst)
                        except Exception:
                            shutil.copy2(src, dst)
                os.environ["PATH"] = extracted_bin + os.pathsep + os.environ.get("PATH", "")
                print(f"[Node Provisioner] Portable Node.js {node_version} successfully configured in {extracted_bin}!", flush=True)
                return True
        except Exception as dl_err:
            print(f"[Node Provisioner] Portable Node download error: {dl_err}", flush=True)

    return False


def install_npm_packages():
    """Runs npm install in the project directory if dependencies are missing."""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    package_json = os.path.join(root_dir, "package.json")
    if not os.path.exists(package_json):
        return

    node_modules = os.path.join(root_dir, "node_modules")
    baileys_dir = os.path.join(node_modules, "@whiskeysockets", "baileys")
    express_dir = os.path.join(node_modules, "express")
    if os.path.exists(baileys_dir) and os.path.exists(express_dir):
        print("[Node Provisioner] Node modules already present. Skipping npm install.", flush=True)
        return

    npm_bin = shutil.which("npm.cmd" if sys.platform == "win32" else "npm") or "npm"
    print(f"[Node Provisioner] Installing npm dependencies using {npm_bin}...", flush=True)
    try:
        subprocess.run([npm_bin, "install"], cwd=root_dir, check=True, timeout=180)
        print("[Node Provisioner] npm dependencies installed successfully!", flush=True)
    except Exception as e:
        print(f"[Node Provisioner] npm install error: {e}", flush=True)


if __name__ == "__main__":
    ensure_node_installed()
    install_npm_packages()
