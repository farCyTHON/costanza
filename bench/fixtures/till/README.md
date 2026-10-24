# till

A counter cash drawer for one shop. Record a sale, void a sale, and print the day's total.

    python -m till sale 12.50 oat-milk
    python -m till void SALE-ID
    python -m till report

The program keeps its data in a SQLite file and uses only the Python standard library. Tests:

    python -m pytest -q
