"""
Script to check and start MySQL service
"""

import subprocess
import sys

def check_mysql_service():
    """Checks for MySQL service"""
    services = ["MySQL", "MySQL80", "MySQL57", "MySQL Server 8.0", "MySQL Server 5.7"]
    
    for service in services:
        try:
            check = subprocess.run(
                ["sc", "query", service],
                capture_output=True,
                text=True,
                shell=True
            )
            if check.returncode == 0:
                print(f"Found service: {service}")
                status = check.stdout
                if "RUNNING" in status:
                    print(f"  Status: RUNNING")
                    return True, service
                elif "STOPPED" in status:
                    print(f"  Status: STOPPED")
                    print(f"\nTo start, run (as admin):")
                    print(f"  net start {service}")
                    return False, service
        except:
            continue
    
    print("MySQL service not found")
    return None, None

def try_start_mysql(service_name):
    """Tries to start MySQL"""
    try:
        print(f"\nTrying to start {service_name}...")
        result = subprocess.run(
            ["net", "start", service_name],
            capture_output=True,
            text=True,
            shell=True
        )
        if result.returncode == 0:
            print(f"MySQL started successfully!")
            return True
        else:
            print(f"Failed to start (need admin rights)")
            print(f"  Run manually: net start {service_name}")
            return False
    except Exception as e:
        print(f"Error: {e}")
        return False

if __name__ == "__main__":
    print("Checking MySQL...")
    print("=" * 50)
    
    found, service_name = check_mysql_service()
    
    if found is True:
        print("\nMySQL is already running!")
        sys.exit(0)
    elif found is False and service_name:
        print("\n" + "=" * 50)
        response = input(f"\nStart {service_name} now? (y/n): ").lower()
        if response == 'y':
            try_start_mysql(service_name)
        else:
            print(f"\nTo start manually (as admin):")
            print(f"  net start {service_name}")
    else:
        print("\n" + "=" * 50)
        print("\nMySQL is not installed or not found.")
        print("\nOptions:")
        print("1. Install MySQL: https://dev.mysql.com/downloads/installer/")
        print("2. Use XAMPP: https://www.apachefriends.org/")
        print("3. Use Docker (if installed)")

