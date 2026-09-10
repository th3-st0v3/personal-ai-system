from db import (
    add_note, get_notes, search_notes,
    create_project, get_projects,
    create_requirement, get_requirement,
    add_evidence, get_evidence_for_requirement,
    get_evidence_history_for_requirement,
    find_matching_evidence,
    update_requirement_status,
    evaluate_requirement_evidence,
    invalidate_evidence,
)

STATUS_CHOICES = {
    "1": "Verified",
    "2": "Failed",
    "3": "Unverified",
    "4": "At risk",
}

while True:
    print("1. Add a note")
    print("2. View notes")
    print("3. Search notes")
    print("4. Ask AI")
    print("5. Create project")
    print("6. List projects")
    print("7. Create requirement")
    print("8. Add evidence")
    print("9. View requirement")
    print("10. Update requirement status")
    print("11. Evaluate requirement evidence")
    print("12. View evidence history")
    print("13. Invalidate evidence")
    print("14. Quit")

    choice = input("Choose an option: ")

    if choice == "1":
        note = input("Enter a note: ")
        add_note(note)
        print("Note saved.")

    elif choice == "2":
        notes = get_notes()
        print("\nYour notes:")
        for note in notes:
            print(f"{note[0]}. {note[1]}")
            print(f"   {note[3]}")

    elif choice == "3":
        query = input("Search for: ")
        notes = search_notes(query)
        print("\nSearch results:")
        for note in notes:
            print(f"{note[0]}. {note[1]}")
            print(f"   {note[3]}")

    elif choice == "4":
        try:
            from model import ask_model
        except ImportError as error:
            print(f"\nAI feature unavailable: {error}")
            continue

        prompt = input("Ask the AI: ")
        try:
            answer = ask_model(prompt)
            print("\nAI:")
            print(answer)
        except Exception as error:
            print(f"\nAI request failed: {error}")

    elif choice == "5":
        name = input("Project name: ")
        description = input("Description (optional): ") or None
        project_id = create_project(name, description)
        print(f"Project created with id {project_id}.")

    elif choice == "6":
        projects = get_projects()
        print("\nProjects:")
        for project in projects:
            print(f"{project[0]}. {project[1]} - {project[2] or ''}")

    elif choice == "7":
        try:
            project_id = int(input("Project id: "))
        except ValueError:
            print("Project id must be a number.")
        else:
            description = input("Requirement description: ")
            requirement_id = create_requirement(project_id, description)
            print(f"Requirement created with id {requirement_id}.")

    elif choice == "8":
        try:
            requirement_id = int(input("Requirement id: "))
        except ValueError:
            print("Requirement id must be a number.")
        else:
            source = input("Evidence source (e.g. test log, datasheet): ")
            location = input("Location (page/section/timestamp, optional): ") or None
            result = input("What did the evidence show?: ")

            print("Does this evidence support:")
            print("1. Verified")
            print("2. Failed")
            print("3. Unverified")
            print("4. At risk")

            supports_status = STATUS_CHOICES.get(input("Choose 1-4: "))

            if supports_status is None:
                print("Invalid choice, evidence not saved.")
            else:
                matches = find_matching_evidence(
                    requirement_id,
                    source,
                    result,
                    supports_status,
                    location,
                )

                save_evidence = True

                if matches:
                    print("\nWarning: matching evidence already exists:")
                    for item in matches:
                        loc = item[3] or "no location given"
                        print(
                            f"  - [{item[5]}] {item[2]} "
                            f"({loc}): {item[4]}"
                        )

                    answer = input("Save this evidence anyway? (y/n): ")
                    save_evidence = answer.strip().lower() == "y"

                if save_evidence:
                    add_evidence(
                        requirement_id,
                        source,
                        result,
                        supports_status,
                        location,
                    )
                    print("Evidence saved.")
                else:
                    print("Evidence not saved.")

    elif choice == "9":
        try:
            requirement_id = int(input("Requirement id: "))
        except ValueError:
            print("Requirement id must be a number.")
        else:
            requirement = get_requirement(requirement_id)

            if requirement is None:
                print("No requirement with that id.")
            else:
                print(f"\nRequirement {requirement[0]}: {requirement[3]}")
                print(f"Project: {requirement[2]}")
                print(f"Status: {requirement[4]}")

                evidence = get_evidence_for_requirement(requirement_id)

                print("Evidence:")

                if not evidence:
                    print("  (no evidence recorded yet)")

                for item in evidence:
                    loc = item[3] or "no location given"
                    print(
                        f"  - [{item[5]}] {item[2]} "
                        f"({loc}): {item[4]}"
                    )

    elif choice == "10":
        try:
            requirement_id = int(input("Requirement id: "))
        except ValueError:
            print("Requirement id must be a number.")
        else:
            print("Set status to:")
            print("1. Verified")
            print("2. Failed")
            print("3. Unverified")
            print("4. At risk")

            new_status = STATUS_CHOICES.get(input("Choose 1-4: "))

            if new_status is None:
                print("Invalid choice, status not changed.")
            else:
                update_requirement_status(requirement_id, new_status)
                print(
                    f"Requirement {requirement_id} "
                    f"status set to {new_status}."
                )

    elif choice == "11":
        try:
            requirement_id = int(input("Requirement id: "))
        except ValueError:
            print("Requirement id must be a number.")
        else:
            requirement = get_requirement(requirement_id)

            if requirement is None:
                print("No requirement with that id.")
            else:
                evaluation = evaluate_requirement_evidence(
                    requirement_id
                )

                print(
                    f"\nRequirement {requirement[0]}: "
                    f"{requirement[3]}"
                )
                print(f"Current status: {requirement[4]}")
                print(
                    "Evidence assessment: "
                    f"{evaluation['recommendation']}"
                )

                signals = evaluation["signals"]

                if signals:
                    print(
                        "Evidence signals: "
                        f"{', '.join(signals)}"
                    )
                else:
                    print("Evidence signals: none")

                print(
                    "Conflict: "
                    f"{'Yes' if evaluation['conflict'] else 'No'}"
                )

                if evaluation["conflict"]:
                    print(
                        "Review conflicting evidence before "
                        "changing the requirement status."
                    )

    elif choice == "12":
        try:
            requirement_id = int(input("Requirement id: "))
        except ValueError:
            print("Requirement id must be a number.")
        else:
            requirement = get_requirement(requirement_id)

            if requirement is None:
                print("No requirement with that id.")
            else:
                history = get_evidence_history_for_requirement(
                    requirement_id
                )

                print(
                    f"\nEvidence history for requirement "
                    f"{requirement[0]}: {requirement[3]}"
                )

                if not history:
                    print("  (no evidence history recorded yet)")

                for item in history:
                    loc = item[3] or "no location given"
                    print(
                        f"  - [{item[5]}] {item[2]} "
                        f"({loc}): {item[4]} "
                        f"[{item[6]}] at {item[7]}"
                    )

    elif choice == "13":
        try:
            evidence_id = int(input("Evidence ID to invalidate: "))
            invalidate_evidence(evidence_id)
            print(f"Evidence {evidence_id} invalidated.")
        except ValueError as error:
            print(f"Error: {error}")

    elif choice == "14":
        print("Goodbye.")
        break

    else:
        print("Invalid option. Please choose 1-14.")
