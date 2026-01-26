#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from string import Template
from dotenv import load_dotenv

def generate_config(template_file: str, output_file: str, **extra_vars):
    """Generate device config from template + .env"""
    
    # Load .env from project root
    project_root = Path(__file__).parent.parent
    env_file = project_root / ".env"
    
    if not env_file.exists():
        print(f"ERROR: {env_file} not found. Copy .env.example to .env first.")
        sys.exit(1)
    
    load_dotenv(env_file)
    
    # Read template
    template_path = Path(__file__).parent / template_file
    if not template_path.exists():
        print(f"ERROR: Template {template_path} not found.")
        sys.exit(1)
    
    with open(template_path) as f:
        template_content = f.read()
    
    # Prepare substitution variables
    vars = {**os.environ, **extra_vars}
    
    # Substitute
    try:
        result = Template(template_content).substitute(vars)
    except KeyError as e:
        print(f"ERROR: Missing required environment variable: {e}")
        sys.exit(1)
    
    # Write output
    output_path = Path(__file__).parent / output_file
    with open(output_path, 'w') as f:
        f.write(result)
    
    print(f"Generated: {output_path}")

if __name__ == "__main__":
    # Generate WisMesh Gateway config
    generate_config(
        "wismesh-gateway-template.yaml.template",
        "wismesh-gateway-config.yaml",
        GATEWAY_OWNER="Gateway1",
        GATEWAY_SHORT="GW01"
    )
    
    # Example: Generate T1000e configs for fleet
    # Uncomment and modify for your vehicles:
    #
    # for vehicle_num in range(1, 41):  # Vehicles 1-40
    #    generate_config(
    #        "t1000e-template.yaml.template",
    #        f"t1000e-vehicle-{vehicle_num:02d}-config.yaml",
    #        DEVICE_OWNER=f"Vehicle {vehicle_num}",
    #        DEVICE_SHORT=f"V{vehicle_num:02d}"
    #   )

    # Example: Generate single T1000e test config files
    # Uncomment and modify as desired
    #
    generate_config(
        "t1000e-template.yaml.template",
        "t1000e-test1-config.yaml",
        DEVICE_OWNER="TestVehicle1",
        DEVICE_SHORT="TEST1"
    )

    generate_config(
        "t1000e-template.yaml.template",
        "t1000e-test2-config.yaml",
        DEVICE_OWNER="TestVehicle2",
        DEVICE_SHORT="TEST2"
    )
