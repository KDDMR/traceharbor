"""Generate a repeatable mix of errors, messages and performance telemetry."""

from __future__ import annotations

import os
import random
import time

from traceharbor_sdk import Client


def checkout(cart_total: float, discount_code: str) -> float:
    if discount_code == "EXPIRED":
        raise ValueError(f"Discount code {discount_code} is no longer valid")
    if cart_total < 0:
        raise ValueError("Cart total cannot be negative")
    return cart_total * 0.9 if discount_code == "WELCOME10" else cart_total


def main() -> None:
    endpoint = os.getenv("TRACEHARBOR_ENDPOINT", "http://127.0.0.1:8080")
    client = Client(
        endpoint,
        os.getenv("TRACEHARBOR_API_KEY", "dev-key"),
        os.getenv("TRACEHARBOR_PROJECT", "demo-store"),
        release="checkout@1.4.0",
        environment="demo",
        batch_size=5,
    )

    client.capture_message("Demo release deployed", tags={"component": "release"})
    for order_id in range(8):
        try:
            with client.transaction(
                "checkout.calculate",
                tags={"region": "eu-central"},
                context={
                    "order_id": order_id,
                    "customer_email": "demo.user@example.com",
                    "authorization": "Bearer this-must-never-be-stored",
                },
            ):
                time.sleep(random.uniform(0.01, 0.06))
                code = "EXPIRED" if order_id % 3 == 0 else "WELCOME10"
                checkout(100 + order_id, code)
        except ValueError:
            # The transaction records both its failed status and the exception.
            pass

    client.close()
    print(f"Sent demo telemetry. Open {endpoint}")


if __name__ == "__main__":
    main()
