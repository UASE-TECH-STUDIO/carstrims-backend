async def create_indexes(db):
    # Users - unique email and username
    await db["users"].create_index("email", unique=True)
    await db["users"].create_index("username", unique=True)
    await db["users"].create_index("role")

    # Dealers
    await db["dealer_organizations"].create_index("userId", unique=True)
    await db["dealer_organizations"].create_index("status")
    await db["dealer_organizations"].create_index("companyName")

    # Cars
    await db["car_listings"].create_index("dealerId")
    await db["car_listings"].create_index("carId", unique=True)
    await db["car_listings"].create_index("status")
    await db["car_listings"].create_index("brand")
    await db["car_listings"].create_index([("brand", 1), ("model", 1)])

    # Sales
    await db["sale_transactions"].create_index("dealerId")
    await db["sale_transactions"].create_index("transactionId", unique=True)
    await db["sale_transactions"].create_index("carId")

    # Staff
    await db["staff_accounts"].create_index("dealerId")
    await db["staff_accounts"].create_index("userId", unique=True)

    # Partners
    await db["partner_links"].create_index([("userId", 1), ("dealerId", 1)])

    # Movements
    await db["vehicle_movement_logs"].create_index("dealerId")
    await db["vehicle_movement_logs"].create_index("carId")

    # Notifications
    await db["notifications"].create_index("receiverId")
    await db["notifications"].create_index("isRead")

    print("MongoDB indexes created successfully")
